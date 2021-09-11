# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2021 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Authors:
#     Nitish Gupta <imnitish.ng@gmail.com>


import json
import logging

import requests
from grimoirelab_toolkit.datetime import (datetime_to_utc,
                                          datetime_utcnow,
                                          str_to_datetime)
from grimoirelab_toolkit.uris import urijoin

from ...backend import (Backend,
                        BackendCommand,
                        BackendCommandArgumentParser,
                        DEFAULT_SEARCH_FIELD)
from ...client import HttpClient, RateLimitHandler
from ...utils import DEFAULT_DATETIME, DEFAULT_LAST_DATETIME

CATEGORY_ISSUE = "issue"
CATEGORY_PULL_REQUEST = "pull_request"

BITBUCKET_URL = "https://bitbucket.org/"
BITBUCKET_API_URL = "https://api.bitbucket.org/2.0"

# Range before sleeping until rate limit reset
MIN_RATE_LIMIT = 10
MAX_RATE_LIMIT = 500

MAX_CATEGORY_ITEMS_PER_PAGE = 100
# PER_PAGE = 100

# Default sleep time and retries to deal with connection/server problems
DEFAULT_SLEEP_TIME = 1
MAX_RETRIES = 5

TARGET_ISSUE_FIELDS = ['reporter', 'assignee', 'links']
TARGET_PULL_FIELDS = ['author', 'closed_by', 'links']
TARGET_ACTIVITY_FIELDS = ['update', 'approval']

logger = logging.getLogger(__name__)


class Bitbucket(Backend):

    version = '0.25.1'

    CATEGORIES = [CATEGORY_ISSUE, CATEGORY_PULL_REQUEST]

    def __init__(self, owner=None, repository=None,
                 api_token=None, base_url=None,
                 tag=None, archive=None,
                 sleep_for_rate=False, min_rate_to_sleep=MIN_RATE_LIMIT,
                 max_retries=MAX_RETRIES, sleep_time=DEFAULT_SLEEP_TIME,
                 max_items=MAX_CATEGORY_ITEMS_PER_PAGE, ssl_verify=True,
                 client_id=None, secret_id=None, refresh_token=None):
        if api_token is None:
            api_token = None
        origin = base_url if base_url else BITBUCKET_URL
        origin = urijoin(origin, owner, repository)

        super().__init__(origin, tag=tag, archive=archive, ssl_verify=ssl_verify)

        self.owner = owner
        self.repository = repository
        self.api_token = api_token
        self.base_url = base_url

        self.sleep_for_rate = sleep_for_rate
        self.min_rate_to_sleep = min_rate_to_sleep
        self.max_retries = max_retries
        self.sleep_time = sleep_time
        self.max_items = max_items

        self.client = None
        self.exclude_user_data = False
        self._users = {}  # internal users cache

        self.client_id = client_id
        self.secret_id = secret_id
        self.refresh_token = refresh_token

    def search_fields(self, item):
        """Add search fields to an item.

        It adds the values of `metadata_id` plus the `owner` and `repo`.

        :param item: the item to extract the search fields values

        :returns: a dict of search fields
        """
        search_fields = {
            DEFAULT_SEARCH_FIELD: self.metadata_id(item),
            'owner': self.owner,
            'repo': self.repository
        }

        return search_fields

    def fetch(self, category=CATEGORY_ISSUE, from_date=DEFAULT_DATETIME, to_date=DEFAULT_LAST_DATETIME,
              filter_classified=False):
        """Fetch the issues/pull requests from the repository.

        The method retrieves, from a Bitbucket repository, the issues/pull requests
        updated since the given date.

        :param category: the category of items to fetch
        :param from_date: obtain issues/pull requests updated since this date
        :param to_date: obtain issues/pull requests until a specific date (included)
        :param filter_classified: remove classified fields from the resulting items

        :returns: a generator of issues
        """
        self.exclude_user_data = filter_classified

        if self.exclude_user_data:
            logger.info("Excluding user data. Personal user information won't be collected from the API.")

        if not from_date:
            from_date = DEFAULT_DATETIME
        if not to_date:
            to_date = DEFAULT_LAST_DATETIME

        from_date = datetime_to_utc(from_date)
        to_date = datetime_to_utc(to_date)

        kwargs = {
            'from_date': from_date,
            'to_date': to_date
        }
        items = super().fetch(category,
                              filter_classified=filter_classified,
                              **kwargs)

        return items

    def fetch_items(self, category, **kwargs):
        """Fetch the items (issues or pull_requests or repo information)

        :param category: the category of items to fetch
        :param kwargs: backend arguments

        :returns: a generator of items
        """
        from_date = kwargs['from_date']
        to_date = kwargs['to_date']

        if category == CATEGORY_ISSUE:
            items = self.__fetch_issues(from_date, to_date)
        elif category == CATEGORY_PULL_REQUEST:
            items = self.__fetch_pull_requests(from_date, to_date)
        # else:
        #     items = self.__fetch_repo_info()

        return items

    def _init_client(self, from_archive=False):
        """Init client"""

        return BitbucketClient(self.owner, self.repository, self.base_url,
                               self.sleep_for_rate, self.min_rate_to_sleep,
                               self.sleep_time, self.max_retries, self.max_items,
                               self.archive, from_archive, self.ssl_verify,
                               self.client_id, self.secret_id, self.refresh_token)

    def __fetch_issues(self, from_date, to_date):
        """Fetch the issues"""

        issues_groups = self.client.issues(from_date=from_date)

        for raw_issues in issues_groups:
            issues = json.loads(raw_issues)
            for issue in issues['values']:

                if str_to_datetime(issue['updated_on']) > to_date:
                    return

                self.__init_extra_issue_fields(issue)
                for field in TARGET_ISSUE_FIELDS:

                    if not issue[field]:
                        continue

                    if field == 'reporter':
                        issue[field + '_data'] = self.__get_user(issue[field]['links']['self'],
                                                                 issue[field]['display_name'])
                    elif field == 'assignee':
                        issue[field + '_data'] = self.__get_issue_assignee(issue[field]['links'],
                                                                           issue[field]['display_name'])
                    elif field == 'links':
                        if 'comments' in issue[field]:
                            issue['comments_data'] = self.__get_issue_comments(issue['id'])

                yield issue

    def __fetch_pull_requests(self, from_date, to_date):
        """Fetch the pull requests"""

        pulls_groups = self.client.pulls(from_date=from_date)

        for raw_pull in pulls_groups:
            pulls = json.loads(raw_pull)
            for pull in pulls['values']:

                if str_to_datetime(pull['updated_on']) > to_date:
                    return

                self.__init_extra_pull_fields(pull)

                pull['activity_data'] = self.__get_pull_activity(pull['id'])

                for field in TARGET_PULL_FIELDS:
                    if not pull[field]:
                        continue

                    if field == 'author':
                        pull[field + '_data'] = self.__get_user(pull[field]['links']['self'],
                                                                pull[field]['display_name'])
                    elif field == 'closed_by':
                        pull[field + '_data'] = self.__get_user(pull[field]['links']['self'],
                                                                pull[field]['display_name'])
                    elif field == 'links':
                        if 'comments' in pull[field]:
                            pull['review_comments_data'] = self.__get_pull_review_comments(pull['id'])
                        if 'commits' in pull[field]:
                            pull['commits_data'] = self.__get_pull_commits(pull['id'])

                yield pull

    def __init_extra_issue_fields(self, issue):
        """Add fields to an issue"""

        issue['reporter_data'] = {}
        issue['assignee_data'] = {}
        issue['comments_data'] = []

    def __init_extra_pull_fields(self, pull):
        """Add fields to a pull request"""

        pull['author_data'] = {}
        pull['review_comments_data'] = {}
        pull['activity_data'] = []
        pull['closed_by_data'] = []
        pull['commits_data'] = []

    @staticmethod
    def metadata_id(item):
        """Extracts the identifier from a Bitbucket item."""

        if "updated_on" in item:
            return str(item['updated_on']) + str(item['id'])

    @staticmethod
    def metadata_updated_on(item):
        """Extracts the update time from a Bitbucket item.

        The timestamp used is extracted from 'updated_on' field.
        This date is converted to UNIX timestamp format. As Bitbucket
        dates are in UTC the conversion is straightforward.

        :param item: item generated by the backend

        :returns: a UNIX timestamp
        """
        ts = item['updated_on']
        ts = str_to_datetime(ts)

        return ts.timestamp()

    @staticmethod
    def metadata_category(item):
        """Extracts the category from a GitHub item.

        This backend generates three types of item which are
        'issue', 'pull_request' and 'repo' information.
        """

        if item['type'] == 'pullrequest':
            category = CATEGORY_PULL_REQUEST
        else:
            category = CATEGORY_ISSUE

        return category

    def __get_user(self, url_user, name):
        """Get user data for the login"""

        if not name or self.exclude_user_data:
            return None

        user_raw = self.client.user(url_user['href'], name)
        user = json.loads(user_raw)

        return user

    def __get_issue_assignee(self, raw_assignee, assignee_name):
        """Get issue assignee"""

        assignee = self.__get_user(raw_assignee['self'], assignee_name)

        return assignee

    def __get_issue_comments(self, issue_number):
        """Get issue comments"""

        comments = []
        group_comments = self.client.issue_comments(issue_number)

        for raw_comments in group_comments:

            comments_parsed = json.loads(raw_comments)['values']
            for comment in comments_parsed:
                if comment['user']:
                    comment['user_data'] = self.__get_user(comment['user']['links']['self'],
                                                           comment['user']['display_name'])
                comments.append(comment)

        return comments

    def __get_pull_review_comments(self, pr_number):
        """Get pull request review comments"""

        comments = []
        group_comments = self.client.pull_review_comments(pr_number)

        for raw_comments in group_comments:

            comments_parsed = json.loads(raw_comments)['values']
            for comment in comments_parsed:
                if comment['user']:
                    comment['user_data'] = self.__get_user(comment['user']['links']['self'],
                                                           comment['user']['display_name'])
                comments.append(comment)

        return comments

    def __get_pull_activity(self, pr_number):
        """Get pull request activities"""

        activities = []
        group_activities = self.client.pull_activities(pr_number)

        for raw_activities in group_activities:

            activities_parsed = json.loads(raw_activities)['values']
            for activity in activities_parsed:
                activity_new = {}
                for act_type in TARGET_ACTIVITY_FIELDS:
                    if act_type in activity.keys():
                        activity_new[act_type] = activity[act_type]
                activities.append(activity_new)

        return activities

    def __get_pull_commits(self, pr_number):
        """Get pull request commit hashes"""

        hashes = []
        try:
            group_pull_commits = self.client.pull_commits(pr_number)

            for raw_pull_commits in group_pull_commits:

                commits_parsed = json.loads(raw_pull_commits)['values']
                for commit in commits_parsed:
                    commit_hash = commit['hash']
                    hashes.append(commit_hash)

        except requests.exceptions.HTTPError:
            return hashes

        return hashes


class BitbucketClient(HttpClient, RateLimitHandler):
    """Client for retieving information from GitHub API

    :param owner: GitHub owner
    :param repository: GitHub repository from the owner
    :param tokens: list of GitHub auth tokens to access the API
    :param base_url: GitHub URL in enterprise edition case;
        when no value is set the backend will be fetch the data
        from the GitHub public site.
    :param sleep_for_rate: sleep until rate limit is reset
    :param min_rate_to_sleep: minimun rate needed to sleep until
         it will be reset
    :param sleep_time: time to sleep in case
        of connection problems
    :param max_retries: number of max retries to a data source
        before raising a RetryError exception
    :param max_items: max number of category items (e.g., issues,
        pull requests) per query
    :param archive: collect issues already retrieved from an archive
    :param from_archive: it tells whether to write/read the archive
    :param ssl_verify: enable/disable SSL verification
    """
    EXTRA_STATUS_FORCELIST = [403, 500, 502, 503]

    _users = {}       # users cache
    _users_orgs = {}  # users orgs cache

    def __init__(self, owner, repository,
                 base_url=None, sleep_for_rate=False, min_rate_to_sleep=MIN_RATE_LIMIT,
                 sleep_time=DEFAULT_SLEEP_TIME, max_retries=MAX_RETRIES,
                 max_items=MAX_CATEGORY_ITEMS_PER_PAGE, archive=None, from_archive=False, ssl_verify=True,
                 client_id=None, secret_id=None, refresh_token=None):
        self.owner = owner
        self.repository = repository
        self.client_id = client_id
        self.secret_id = secret_id
        self.refresh_token = refresh_token
        self.current_token = None
        self.last_rate_limit_checked = None
        self.max_items = max_items

        if base_url:
            base_url = urijoin(base_url, 'api', 'v3')
        else:
            base_url = BITBUCKET_API_URL

        super().__init__(base_url, sleep_time=sleep_time, max_retries=max_retries,
                         extra_status_forcelist=self.EXTRA_STATUS_FORCELIST,
                         archive=archive, from_archive=from_archive, ssl_verify=ssl_verify)
        super().setup_rate_limit_handler(sleep_for_rate=sleep_for_rate, min_rate_to_sleep=min_rate_to_sleep)

        # Extract Access token
        if not self.from_archive:
            self._extract_access_token(self.client_id, self.secret_id, self.refresh_token)

    def _extract_access_token(self, client_id, secret_id, refresh_token):
        """Extract Access token from Bitbucket Client ID, Secret ID and Refresh Token"""

        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
        response = requests.post('https://bitbucket.org/site/oauth2/access_token', data=data,
                                 auth=(client_id, secret_id))

        self.access_token = json.loads(response.text)['access_token']
        self.session.headers.update({'Authorization': 'Bearer ' + self.access_token})

    def fetch_items(self, path, payload):
        """Return the items from bitbucket API using links pagination"""

        page = 0  # current page
        url_next = urijoin(self.base_url, 'repositories', self.owner, self.repository, path)
        logger.debug("Get Bitbucket paginated items from " + url_next)

        response = self.fetch(url_next, payload=payload)

        items = response.text
        data = json.loads(response.text)
        page += 1

        while items:
            yield items

            items = None

            if 'next' in data.keys():
                url_next = data['next']
                response = self.fetch(url_next, payload=payload)
                page += 1

                items = response.text
                data = json.loads(response.text)
                logger.debug("Page: %i" % (page))

    def issues(self, from_date=None):
        """Fetch the issues from the repository.

        The method retrieves, from a Bitbucket repository, the issues
        updated since the given date.

        :param from_date: obtain issues updated since this date

        :returns: a generator of issues
        """

        payload = {'sort': 'updated_on'}

        if from_date:
            payload['q'] = 'updated_on >= ' + from_date.isoformat()

        path = urijoin("issues")
        return self.fetch_items(path, payload)

    def pulls(self, from_date=None):
        """Fetch the pull requests from the repository.

        The method retrieves, from a Bitbucket repository, the pull requests
        updated since the given date.

        :param from_date: obtain pull requests updated since this date

        :returns: a generator of pull requests
        """

        # Collect all 4 types of pull requests
        payload = {'sort': 'updated_on',
                   'state': 'MERGED+OPEN+DECLINED+SUPERSEDED'}

        if from_date:
            payload['q'] = 'updated_on >= ' + from_date.isoformat()

        path = urijoin("pullrequests")
        return self.fetch_items(path, payload)

    def fetch(self, url, payload=None, headers=None, method=HttpClient.GET, stream=False, auth=None):
        """Fetch the data from a given URL.

        :param url: link to the resource
        :param payload: payload of the request
        :param headers: headers of the request
        :param method: type of request call (GET or POST)
        :param stream: defer downloading the response body until the response content is available
        :param auth: auth of the request

        :returns a response object
        """
        if not self.from_archive:
            self.sleep_for_rate_limit()

        response = super().fetch(url, payload, headers, method, stream, auth)

        if not self.from_archive:
            self.update_rate_limit(response)

        return response

    def user(self, url_user, name):
        """Get the user information and update the user cache"""
        user = None

        if name in self._users:
            return self._users[name]

        logger.debug("Getting info for %s" % name)

        r = self.fetch(url_user)
        user = r.text
        self._users[name] = user

        return user

    def pull_commits(self, pr_number):
        """Get pull request commits"""

        payload = {}

        commit_url = urijoin("pullrequests", str(pr_number), "commits")
        return self.fetch_items(commit_url, payload)

    def issue_comments(self, issue_number):
        """Get the issue comments from pagination"""

        payload = {}
        path = urijoin("issues", str(issue_number), "comments")

        return self.fetch_items(path, payload)

    def pull_review_comments(self, pr_number):
        """Get pull request review comments"""

        payload = {}
        comments_url = urijoin("pullrequests", str(pr_number), "comments")

        return self.fetch_items(comments_url, payload)

    def pull_activities(self, pr_number):
        """Get pull request activities"""

        payload = {}
        activities_url = urijoin("pullrequests", str(pr_number), "activity")

        return self.fetch_items(activities_url, payload)


class Bitbucket(BackendCommand):

    BACKEND = Bitbucket

    @classmethod
    def setup_cmd_parser(cls):
        """Returns the Bitbucket argument parser."""

        parser = BackendCommandArgumentParser(cls.BACKEND,
                                              from_date=True,
                                              to_date=True,
                                              token_auth=False,
                                              archive=True,
                                              ssl_verify=True)
        # Bitbucket options
        group = parser.parser.add_argument_group('Bitbucket arguments')
        group.add_argument('--enterprise-url', dest='base_url',
                           help="Base URL for Bitbucket instance")
        group.add_argument('--sleep-for-rate', dest='sleep_for_rate',
                           action='store_true',
                           help="sleep for getting more rate")
        group.add_argument('--min-rate-to-sleep', dest='min_rate_to_sleep',
                           default=MIN_RATE_LIMIT, type=int,
                           help="sleep until reset when the rate limit reaches this value")

        # Bitbucket token(s)
        group.add_argument('-c', '--client-id', dest='client_id',
                           default=None,
                           help="Bitbucket key")
        group.add_argument('-s', '--secret-id', dest='secret_id',
                           default=None,
                           help="Bitbucket secret token")
        group.add_argument('-r', '--refresh-token', dest='refresh_token',
                           default=None,
                           help="Bitbucket refresh token")

        # Generic client options
        group.add_argument('--max-items', dest='max_items',
                           default=MAX_CATEGORY_ITEMS_PER_PAGE, type=int,
                           help="Max number of category items per query.")
        group.add_argument('--max-retries', dest='max_retries',
                           default=MAX_RETRIES, type=int,
                           help="number of API call retries")
        group.add_argument('--sleep-time', dest='sleep_time',
                           default=DEFAULT_SLEEP_TIME, type=int,
                           help="sleeping time between API call retries")

        # Positional arguments
        parser.parser.add_argument('owner',
                                   help="Bitbucket owner")
        parser.parser.add_argument('repository',
                                   help="Bitbucket repository")

        return parser
