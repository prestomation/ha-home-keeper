# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                   |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py        |      266 |      266 |       20 |        0 |      0% |     8-826 |
| custom\_components/home\_keeper/assets.py              |      304 |       12 |      142 |       11 |     95% |96, 149, 154, 161, 198-199, 201, 230, 276, 304-\>306, 393, 489-490, 526-\>528 |
| custom\_components/home\_keeper/binary\_sensor.py      |       28 |       28 |        0 |        0 |      0% |      3-54 |
| custom\_components/home\_keeper/button.py              |       22 |       22 |        0 |        0 |      0% |      8-55 |
| custom\_components/home\_keeper/calendar.py            |       72 |       72 |       32 |        0 |      0% |     9-132 |
| custom\_components/home\_keeper/card.py                |       15 |       15 |        2 |        0 |      0% |     10-37 |
| custom\_components/home\_keeper/companions.py          |       83 |       83 |       16 |        0 |      0% |    27-230 |
| custom\_components/home\_keeper/companions\_catalog.py |       39 |        1 |       12 |        0 |     98% |        60 |
| custom\_components/home\_keeper/config\_flow.py        |       27 |       27 |        4 |        0 |      0% |    10-114 |
| custom\_components/home\_keeper/const.py               |       87 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/coordinator.py         |       77 |       77 |       22 |        0 |      0% |     8-221 |
| custom\_components/home\_keeper/device\_trigger.py     |       61 |       61 |       22 |        0 |      0% |    23-163 |
| custom\_components/home\_keeper/devices.py             |      130 |      130 |       60 |        0 |      0% |    13-287 |
| custom\_components/home\_keeper/diagnostics.py         |       10 |       10 |        0 |        0 |      0% |      9-26 |
| custom\_components/home\_keeper/entity.py              |       18 |       18 |        2 |        0 |      0% |     16-43 |
| custom\_components/home\_keeper/events.py              |       22 |        1 |        6 |        1 |     93% |42-\>44, 129 |
| custom\_components/home\_keeper/inventory.py           |       64 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/models.py              |      233 |       13 |      120 |        5 |     95% |67, 140-141, 151-152, 158-159, 186, 212, 216, 298, 302-303 |
| custom\_components/home\_keeper/notifications.py       |       96 |        6 |       38 |        3 |     92% |115-117, 155, 172, 201-\>203, 216 |
| custom\_components/home\_keeper/notifier.py            |      139 |      139 |       54 |        0 |      0% |    14-353 |
| custom\_components/home\_keeper/options.py             |       47 |       47 |       16 |        0 |      0% |    15-135 |
| custom\_components/home\_keeper/panel.py               |       22 |       22 |        4 |        0 |      0% |     10-70 |
| custom\_components/home\_keeper/problem\_sync.py       |      107 |      107 |       34 |        0 |      0% |    10-205 |
| custom\_components/home\_keeper/problem\_tasks.py      |       62 |        2 |       26 |        1 |     97% |   170-171 |
| custom\_components/home\_keeper/profiles.py            |       64 |        3 |       28 |        0 |     95% |     66-68 |
| custom\_components/home\_keeper/reconcile.py           |       72 |        0 |       40 |        0 |    100% |           |
| custom\_components/home\_keeper/recurrence.py          |      194 |       10 |      102 |       10 |     93% |53, 106, 136, 173, 184, 213, 258, 294, 318, 478 |
| custom\_components/home\_keeper/sensor.py              |       77 |       77 |       18 |        0 |      0% |    13-154 |
| custom\_components/home\_keeper/sensor\_tasks.py       |       65 |        1 |       28 |        1 |     98% |        88 |
| custom\_components/home\_keeper/sensor\_watcher.py     |      107 |      107 |       42 |        0 |      0% |    18-217 |
| custom\_components/home\_keeper/store.py               |      350 |      350 |      136 |        0 |      0% |     9-767 |
| custom\_components/home\_keeper/todo.py                |       42 |       42 |        8 |        0 |      0% |     10-99 |
| custom\_components/home\_keeper/transitions.py         |       31 |        0 |       10 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py      |      282 |      282 |       56 |        0 |      0% |     8-512 |
| **TOTAL**                                              | **3315** | **2031** | **1114** |   **32** | **41%** |           |


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