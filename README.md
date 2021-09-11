# perceval-bitbucket
[![Build Status](https://github.com/perceval-backends/grimoirelab-perceval-bitbucket/workflows/tests/badge.svg)](https://github.com/perceval-backends/grimoirelab-perceval-bitbucket/actions?query=workflow:tests+branch:master+event:push) [![Coverage Status](https://img.shields.io/coveralls/perceval-backends/grimoirelab-perceval-bitbucket.svg)](https://coveralls.io/r/perceval-backends/grimoirelab-perceval-bitbucket?branch=master) [![PyPI version](https://badge.fury.io/py/perceval-bitbucket.svg)](https://badge.fury.io/py/perceval-bitbucket)

Perceval backend for Bitbucket.

## Requirements

* Python >= 3.6.1
* python3-requests >= 2.7
* grimoirelab-toolkit >= 0.2
* perceval >= 0.17.4

## Installation

### Getting the source code

Clone the repository
```
$ git clone https://github.com/perceval-backends/grimoirelab-perceval-bitbucket
```

### Prerequisites

#### Poetry

We use [Poetry](https://python-poetry.org/docs/) for managing the project. You can install it following [these steps](https://python-poetry.org/docs/#installation).

### Setup

Install the required dependencies (this will also create a virtual environment)
```
$ poetry install
```

Activate the virtual environment
```
$ poetry shell
```

## Usage

**Note**:

3 tokens are needed to access the bitbucket backend
- `CLIENT_ID` get from [Bitbucket - Settings](https://bitbucket.org/account/settings/)
- `SECRET_ID` get from [Bitbucket - Settings](https://bitbucket.org/account/settings/)
- `REFRESH_TOKEN`

For getting `REFRESH_TOKEN` from Bitbucket one needs to follow these steps -

- Go to `https://bitbucket.org/site/oauth2/authorize?client_id={CLIENT_ID}&response_type=code` in your preferred browser
- Authorize under your bitbucket account
- The page will be redirected to `{YOUR_REDIRECT_LINK}/?code={CODE}`
- Use [curl](https://curl.se/) with the required parameters
```
$ curl -X POST -u {CLIENT_ID}:{SECRET_ID} https://bitbucket.org/site/oauth2/token -d grant_type=authorization_code -d code={CODE}
```
- The response will be a JSON containing out `REFRESH_TOKEN`

Fetch issues from the bitbucket project [libqxt/libqxt](https://bitbucket.org/libqxt/libqxt) with `CLIENT_ID`, `SECRET_ID`, `REFRESH_TOKEN`
```
$ perceval bitbucket libqxt libqxt --category issue -c CLIENT_ID -s SECRET_ID -r REFRESH_TOKEN
```

The bitbucket backend can fetch `issue` and `pull_request`.

## Roadmap

- [ ] Fix flake8 errors
- [ ] Add support for using `username` and `password` for authentication instead of the 3 access tokens, read more about it from [chaoss/grimoirelab-perceval/#/653 (comment)](https://github.com/chaoss/grimoirelab-perceval/pull/653#issuecomment-618886424)
- [ ] Add [tests](https://github.com/perceval-backends/grimoirelab-perceval-bitbucket/blob/master/tests/test_bitbucket.py)
- [ ] Start using [Bitergia/release-tools](https://github.com/Bitergia/release-tools)
- [ ] Publish the package to [PyPI](https://pypi.org/)

## Contributing

This project follows the [contributing guidelines](https://github.com/chaoss/grimoirelab/blob/master/CONTRIBUTING.md) of the GrimoireLab.

## Acknowledgment

The backend was initially developed by [@imnitishng](https://github.com/imnitishng).

Adhering to the guidelines, the work is moved to this external repository. But, this can be merged ([chaoss/grimoirelab-perceval/#/653](https://github.com/chaoss/grimoirelab-perceval/pull/653)) into the [Perceval](https://github.com/chaoss/grimoirelab-perceval) repository in the future.

## License

Licensed under GNU General Public License (GPL), version 3 or later.
