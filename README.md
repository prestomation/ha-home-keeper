# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                   |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py        |      223 |      223 |       18 |        0 |      0% |     8-670 |
| custom\_components/home\_keeper/assets.py              |      304 |       12 |      142 |       11 |     95% |96, 149, 154, 161, 198-199, 201, 230, 276, 304-\>306, 393, 489-490, 526-\>528 |
| custom\_components/home\_keeper/binary\_sensor.py      |       28 |       28 |        0 |        0 |      0% |      3-54 |
| custom\_components/home\_keeper/button.py              |       22 |       22 |        0 |        0 |      0% |      8-55 |
| custom\_components/home\_keeper/calendar.py            |       72 |       72 |       32 |        0 |      0% |     9-132 |
| custom\_components/home\_keeper/card.py                |       15 |       15 |        2 |        0 |      0% |     10-37 |
| custom\_components/home\_keeper/companions.py          |       83 |       83 |       16 |        0 |      0% |    27-230 |
| custom\_components/home\_keeper/companions\_catalog.py |       39 |        1 |       12 |        0 |     98% |        60 |
| custom\_components/home\_keeper/config\_flow.py        |       27 |       27 |        4 |        0 |      0% |    10-107 |
| custom\_components/home\_keeper/const.py               |       70 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/coordinator.py         |       70 |       70 |       18 |        0 |      0% |     8-197 |
| custom\_components/home\_keeper/device\_trigger.py     |       61 |       61 |       22 |        0 |      0% |    23-159 |
| custom\_components/home\_keeper/devices.py             |      130 |      130 |       60 |        0 |      0% |    13-287 |
| custom\_components/home\_keeper/diagnostics.py         |       10 |       10 |        0 |        0 |      0% |      9-26 |
| custom\_components/home\_keeper/entity.py              |       18 |       18 |        2 |        0 |      0% |     16-43 |
| custom\_components/home\_keeper/events.py              |       22 |        1 |        6 |        1 |     93% |42-\>44, 129 |
| custom\_components/home\_keeper/inventory.py           |       64 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/models.py              |      166 |        7 |       86 |        5 |     95% |63, 110, 136, 140, 214, 218-219 |
| custom\_components/home\_keeper/options.py             |       42 |       42 |       12 |        0 |      0% |    15-120 |
| custom\_components/home\_keeper/panel.py               |       22 |       22 |        4 |        0 |      0% |     10-70 |
| custom\_components/home\_keeper/problem\_sync.py       |      104 |      104 |       32 |        0 |      0% |    10-201 |
| custom\_components/home\_keeper/problem\_tasks.py      |       62 |        2 |       26 |        1 |     97% |   170-171 |
| custom\_components/home\_keeper/reconcile.py           |       72 |        0 |       40 |        0 |    100% |           |
| custom\_components/home\_keeper/recurrence.py          |      180 |       10 |       96 |       10 |     93% |52, 105, 135, 172, 183, 212, 256, 292, 314, 434 |
| custom\_components/home\_keeper/sensor.py              |       77 |       77 |       18 |        0 |      0% |    13-154 |
| custom\_components/home\_keeper/store.py               |      309 |      309 |      122 |        0 |      0% |     9-658 |
| custom\_components/home\_keeper/todo.py                |       41 |       41 |        8 |        0 |      0% |     10-98 |
| custom\_components/home\_keeper/transitions.py         |       31 |        0 |       10 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py      |      273 |      273 |       54 |        0 |      0% |     8-480 |
| **TOTAL**                                              | **2637** | **1660** |  **856** |   **28** | **40%** |           |


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