# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                             |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py                  |      604 |      604 |       74 |        0 |      0% |    8-2057 |
| custom\_components/home\_keeper/api\_surface.py                  |       87 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/appliance\_report.py             |       66 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/assets.py                        |      711 |       29 |      310 |       23 |     95% |163, 192, 211, 216, 223, 256, 280, 283, 286, 309-310, 347, 349, 354, 368-\>367, 416-417, 419, 593, 596, 599-600, 606, 642, 759, 1392, 1658-1659, 1683-1684, 1686-\>1699, 1732-\>1734 |
| custom\_components/home\_keeper/backend\_i18n.py                 |       46 |        6 |        8 |        2 |     85% |62, 65-66, 69, 91-92 |
| custom\_components/home\_keeper/binary\_sensor.py                |       69 |       69 |        6 |        0 |      0% |    12-151 |
| custom\_components/home\_keeper/button.py                        |       31 |       31 |        2 |        0 |      0% |     12-81 |
| custom\_components/home\_keeper/calendar.py                      |       83 |       12 |       40 |        9 |     83% |34-35, 59-60, 74, 78-\>72, 90, 94, 123, 128, 136, 138, 142, 159-\>134 |
| custom\_components/home\_keeper/card.py                          |       86 |        7 |       28 |        2 |     92% |87-89, 122-123, 127, 146 |
| custom\_components/home\_keeper/card\_resource.py                |       29 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/companions.py                    |       86 |       34 |       18 |        2 |     54% |62, 108, 138-\>140, 145, 149-153, 157, 173-196, 201-205, 211-213, 223, 229, 235, 247-248 |
| custom\_components/home\_keeper/companions\_catalog.py           |       40 |        1 |       12 |        0 |     98% |        61 |
| custom\_components/home\_keeper/config\_flow.py                  |       30 |        7 |        4 |        1 |     71% |143-149, 155, 178 |
| custom\_components/home\_keeper/const.py                         |      192 |        2 |       12 |        1 |     99% |  955, 967 |
| custom\_components/home\_keeper/coordinator.py                   |      141 |       72 |       48 |        3 |     43% |58, 63, 86-128, 144, 148, 174, 184, 186-\>exit, 198-201, 204-262, 312, 324, 334, 345, 358-368, 399-410, 430-434 |
| custom\_components/home\_keeper/declarative\_companion\_sync.py  |      185 |      123 |       32 |        1 |     31% |77-78, 111-133, 153-154, 168-194, 205-210, 221-225, 235, 246-250, 254, 273, 304-308, 330-363, 386-406, 414, 421, 428, 433, 438, 441-458, 461-464, 469, 475, 488-554, 569-574 |
| custom\_components/home\_keeper/declarative\_companions.py       |      367 |        3 |      182 |        3 |     99% |136, 262, 264 |
| custom\_components/home\_keeper/declarative\_preset\_text.py     |        2 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_presets.py          |       95 |        0 |       34 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_presets\_catalog.py |        3 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/device\_compat.py                |       17 |        0 |        6 |        0 |    100% |           |
| custom\_components/home\_keeper/device\_trigger.py               |       69 |       69 |       24 |        0 |      0% |    23-163 |
| custom\_components/home\_keeper/devices.py                       |      217 |      121 |      112 |        2 |     43% |57, 74, 85-87, 92, 97-107, 116, 123-124, 140-146, 161-193, 249-\>256, 348, 380-390, 411-424, 436-503, 511-538, 595-603 |
| custom\_components/home\_keeper/diagnostics.py                   |       23 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/documents.py                     |       61 |        1 |       26 |        1 |     98% |       141 |
| custom\_components/home\_keeper/entity.py                        |       46 |       46 |        8 |        0 |      0% |    27-125 |
| custom\_components/home\_keeper/events.py                        |       27 |        0 |        8 |        0 |    100% |           |
| custom\_components/home\_keeper/manuals.py                       |      314 |      314 |       66 |        0 |      0% |    21-784 |
| custom\_components/home\_keeper/models.py                        |      459 |       10 |      276 |        6 |     98% |194, 197-198, 204, 518, 661, 665, 758, 762-763 |
| custom\_components/home\_keeper/notifications.py                 |      229 |        5 |       76 |        1 |     98% |355, 467-468, 476-477 |
| custom\_components/home\_keeper/notifier.py                      |      173 |       82 |       74 |       10 |     46% |61-62, 102-104, 106-108, 130-132, 137-142, 152-153, 247, 297-306, 321-326, 361-\>378, 366, 374, 379-381, 404-414, 421, 439-556 |
| custom\_components/home\_keeper/number.py                        |       72 |       72 |       14 |        0 |      0% |    11-159 |
| custom\_components/home\_keeper/options.py                       |       72 |        0 |       28 |        0 |    100% |           |
| custom\_components/home\_keeper/panel.py                         |       29 |       29 |        4 |        0 |      0% |    10-107 |
| custom\_components/home\_keeper/problem\_sync.py                 |      113 |      113 |       40 |        0 |      0% |    10-219 |
| custom\_components/home\_keeper/problem\_tasks.py                |       65 |        2 |       26 |        1 |     97% |   200-201 |
| custom\_components/home\_keeper/profiles.py                      |      106 |        1 |       50 |        1 |     99% |       132 |
| custom\_components/home\_keeper/reconcile.py                     |      318 |        5 |      168 |        7 |     98% |190, 210, 316, 318, 392, 773-\>781, 854-\>852 |
| custom\_components/home\_keeper/recurrence.py                    |      333 |        7 |      156 |        7 |     97% |196, 288, 300, 333, 393, 558, 910 |
| custom\_components/home\_keeper/resolve.py                       |       50 |        0 |       16 |        0 |    100% |           |
| custom\_components/home\_keeper/sensor.py                        |      164 |      164 |       42 |        0 |      0% |    16-382 |
| custom\_components/home\_keeper/sensor\_tasks.py                 |      184 |        3 |       76 |        4 |     97% |144, 177-\>172, 196, 202 |
| custom\_components/home\_keeper/sensor\_watcher.py               |      267 |      200 |      114 |        0 |     19% |79, 93-96, 102, 113-122, 131, 142-143, 166-181, 240-256, 271-279, 291-322, 327, 334-339, 358-419, 424-426, 430-432, 442-444, 449-451, 462-465, 477-478, 483-489, 497, 510-581, 586-600, 614-620, 625-626, 641-642, 657-658, 705-706, 736-742, 758-776 |
| custom\_components/home\_keeper/shopping.py                      |      206 |        0 |       92 |        0 |    100% |           |
| custom\_components/home\_keeper/shopping\_sync.py                |      103 |       10 |       40 |        8 |     86% |89-92, 115, 140, 150, 183-\>173, 230, 232, 233-\>235, 242 |
| custom\_components/home\_keeper/store.py                         |     1020 |      670 |      452 |       41 |     30% |116, 130-131, 156-158, 176, 249, 259, 267-279, 291-294, 296, 303, 305, 314, 335, 350, 354, 369-373, 398, 401, 415-433, 444-454, 461-496, 533, 540, 564, 569, 571, 613-627, 654-676, 707-726, 753-792, 809-824, 827-860, 873-880, 890-896, 906-920, 925, 928, 931, 936-942, 947-963, 994-1046, 1060-1071, 1084-1089, 1100-1112, 1124-1130, 1143-1149, 1160-1174, 1180-1189, 1198-1200, 1217-1230, 1241-1250, 1260-1267, 1299-1344, 1352-1355, 1433-\>1444, 1446, 1454-1455, 1458, 1469, 1475-1476, 1484, 1501-1507, 1511-1517, 1532-1580, 1596-1625, 1646-1656, 1673-1708, 1713, 1716, 1733-1753, 1765-1797, 1809-1830, 1841-1853, 1883-1944, 1981, 1991, 2003-2007, 2025-2026, 2069-2098, 2110-2130, 2153, 2164, 2178-2180, 2211-2249, 2267-2294, 2301-2316, 2331-2358, 2371-2387, 2396-2409, 2430-2433, 2453, 2458, 2466, 2469, 2483-\>exit, 2514, 2522-\>exit, 2557-2567, 2601, 2604 |
| custom\_components/home\_keeper/tag\_listener.py                 |       29 |       29 |        8 |        0 |      0% |     12-69 |
| custom\_components/home\_keeper/tags.py                          |       11 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_counts.py                  |       20 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_entities.py                |       33 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/template\_context.py             |       50 |       10 |       18 |        4 |     74% |109, 149-151, 155-157, 160-162 |
| custom\_components/home\_keeper/todo.py                          |       64 |        6 |       20 |        0 |     93% |41-42, 58-59, 152-153 |
| custom\_components/home\_keeper/todo\_items.py                   |       30 |        0 |       16 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list.py                    |      234 |        0 |       98 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list\_sync.py              |      120 |        2 |       48 |        2 |     98% |  187, 201 |
| custom\_components/home\_keeper/todo\_sync\_driver.py            |      103 |        4 |       26 |        3 |     95% |124, 204-\>210, 230-231, 278 |
| custom\_components/home\_keeper/transfer.py                      |      523 |        9 |      212 |        5 |     98% |274-283, 526-\>537, 752, 771, 1231-\>1230, 1359-\>1362 |
| custom\_components/home\_keeper/transfer\_runner.py              |       43 |       43 |       14 |        0 |      0% |    13-141 |
| custom\_components/home\_keeper/transitions.py                   |       31 |        0 |       10 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py                |      592 |      592 |       78 |        0 |      0% |    8-1595 |
| **TOTAL**                                                        | **9573** | **3619** | **3384** |  **150** | **63%** |           |


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