# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                              |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py   |      162 |      162 |       16 |        0 |      0% |     8-388 |
| custom\_components/home\_keeper/assets.py         |      260 |        9 |      122 |        8 |     96% |99, 150-151, 153, 182, 225, 255-\>259, 311, 409-410, 446-\>448 |
| custom\_components/home\_keeper/binary\_sensor.py |       29 |       29 |        0 |        0 |      0% |      3-57 |
| custom\_components/home\_keeper/button.py         |       21 |       21 |        0 |        0 |      0% |      8-48 |
| custom\_components/home\_keeper/calendar.py       |       68 |       68 |       28 |        0 |      0% |     9-125 |
| custom\_components/home\_keeper/config\_flow.py   |       13 |       13 |        2 |        0 |      0% |      7-32 |
| custom\_components/home\_keeper/const.py          |       36 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/coordinator.py    |       46 |       46 |       10 |        0 |      0% |     8-135 |
| custom\_components/home\_keeper/devices.py        |      128 |      128 |       58 |        0 |      0% |    13-286 |
| custom\_components/home\_keeper/diagnostics.py    |       10 |       10 |        0 |        0 |      0% |      9-26 |
| custom\_components/home\_keeper/entity.py         |       18 |       18 |        2 |        0 |      0% |     16-43 |
| custom\_components/home\_keeper/events.py         |        6 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/inventory.py      |       53 |        0 |        8 |        0 |    100% |           |
| custom\_components/home\_keeper/models.py         |       59 |        5 |       20 |        3 |     90% |49, 53, 82, 86-87 |
| custom\_components/home\_keeper/panel.py          |       22 |       22 |        4 |        0 |      0% |     10-70 |
| custom\_components/home\_keeper/reconcile.py      |       71 |        0 |       38 |        0 |    100% |           |
| custom\_components/home\_keeper/recurrence.py     |      126 |       11 |       60 |       11 |     88% |47, 93, 109, 133, 144, 173, 204, 219, 235, 275, 283 |
| custom\_components/home\_keeper/sensor.py         |       62 |       62 |       10 |        0 |      0% |    12-133 |
| custom\_components/home\_keeper/store.py          |      202 |      202 |       78 |        0 |      0% |     9-377 |
| custom\_components/home\_keeper/todo.py           |       34 |       34 |        6 |        0 |      0% |     10-76 |
| custom\_components/home\_keeper/websocket\_api.py |      220 |      220 |       46 |        0 |      0% |     8-366 |
| **TOTAL**                                         | **1646** | **1060** |  **508** |   **22** | **38%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/prestomation/ha-home-keeper/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prestomation/ha-home-keeper/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fprestomation%2Fha-home-keeper%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.