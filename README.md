# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                             |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py                  |      648 |      648 |       78 |        0 |      0% |    8-2184 |
| custom\_components/home\_keeper/api\_surface.py                  |       87 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/appliance\_report.py             |       68 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/assets.py                        |      734 |       19 |      320 |       18 |     96% |164, 197, 216, 221, 265, 289, 292, 295, 398-\>397, 451, 626, 629, 640, 676, 793, 1453, 1726-1727, 1751-1752, 1754-\>1767 |
| custom\_components/home\_keeper/backend\_i18n.py                 |       49 |        5 |        8 |        1 |     89% |76-77, 80, 108-109 |
| custom\_components/home\_keeper/binary\_sensor.py                |       69 |       69 |        6 |        0 |      0% |    12-151 |
| custom\_components/home\_keeper/button.py                        |       41 |       13 |        4 |        0 |     67% |39-61, 73-74 |
| custom\_components/home\_keeper/calendar.py                      |       95 |        8 |       40 |        7 |     89% |35-36, 102, 106-\>100, 128, 157, 162, 170, 176, 202-\>168 |
| custom\_components/home\_keeper/card.py                          |       86 |        7 |       28 |        2 |     92% |87-89, 122-123, 127, 146 |
| custom\_components/home\_keeper/card\_resource.py                |       29 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/companions.py                    |       86 |       33 |       18 |        2 |     55% |62, 108, 138-\>140, 157-161, 165, 181-204, 209-213, 219-221, 231, 237, 243, 255-256 |
| custom\_components/home\_keeper/companions\_catalog.py           |       40 |        1 |       12 |        0 |     98% |        61 |
| custom\_components/home\_keeper/config\_flow.py                  |       30 |        7 |        4 |        1 |     71% |147-153, 159, 182 |
| custom\_components/home\_keeper/const.py                         |      199 |        1 |       12 |        1 |     99% |       984 |
| custom\_components/home\_keeper/coordinator.py                   |      179 |       71 |       60 |        3 |     56% |116-121, 130-175, 204, 208, 254, 264, 266-\>exit, 280-283, 286-344, 396, 408, 418, 429, 442-452, 483-494 |
| custom\_components/home\_keeper/declarative\_companion\_sync.py  |      235 |      103 |       52 |        1 |     57% |78-79, 122-162, 182-183, 197-224, 235-240, 251-255, 265, 276-280, 284, 303, 334-338, 460-480, 488, 495, 502, 507-508, 581, 587, 600-670, 685-692, 702-707 |
| custom\_components/home\_keeper/declarative\_companions.py       |      393 |        3 |      196 |        3 |     99% |136, 262, 264 |
| custom\_components/home\_keeper/declarative\_preset\_text.py     |        2 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_presets.py          |      152 |        0 |       58 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_presets\_catalog.py |        3 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/device\_compat.py                |       52 |        0 |       20 |        0 |    100% |           |
| custom\_components/home\_keeper/device\_trigger.py               |       69 |       69 |       24 |        0 |      0% |    23-163 |
| custom\_components/home\_keeper/devices.py                       |      244 |       59 |      134 |       16 |     74% |71-73, 78, 87-90, 92, 102, 118-124, 149-151, 155-\>146, 175-181, 237-\>244, 342, 389-399, 420-433, 501, 511, 518, 529-530, 537-\>540, 556-562, 570-571, 573-574, 602-\>exit, 636-644 |
| custom\_components/home\_keeper/diagnostics.py                   |       23 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/documents.py                     |       93 |        1 |       34 |        1 |     98% |       209 |
| custom\_components/home\_keeper/entity.py                        |       51 |       27 |        8 |        0 |     41% |51-70, 74, 95-103, 107-108, 116-117, 135-140 |
| custom\_components/home\_keeper/events.py                        |       27 |        0 |        8 |        0 |    100% |           |
| custom\_components/home\_keeper/manuals.py                       |      467 |      143 |      102 |       24 |     66% |138-139, 188-191, 214-220, 239, 282, 300-302, 328-\>exit, 365-374, 379, 384, 405, 432-434, 457-460, 498-505, 519-524, 557-558, 573, 575-576, 578, 585-586, 592-594, 598-\>600, 603-605, 633-\>635, 636-637, 638-\>644, 667-685, 706-707, 710-711, 714-715, 743-\>exit, 761-766, 783, 788, 797-799, 819-824, 840-845, 850-861, 889-894, 909, 912-915, 919, 926-928, 930, 946-949, 969-980, 1021-1022, 1047-1048, 1057, 1068, 1089-1092, 1121-1126 |
| custom\_components/home\_keeper/models.py                        |      528 |        8 |      324 |        6 |     98% |224, 235, 600, 743, 747, 841, 845-846 |
| custom\_components/home\_keeper/notifications.py                 |      267 |        5 |       92 |        1 |     98% |365, 555-556, 564-565 |
| custom\_components/home\_keeper/notifier.py                      |      209 |       23 |       88 |       15 |     87% |61-62, 102-104, 108, 132, 142, 284, 374, 391, 438, 446, 453, 478, 493, 518-520, 552, 631-638, 655-\>exit, 671 |
| custom\_components/home\_keeper/number.py                        |       72 |       72 |       14 |        0 |      0% |    11-159 |
| custom\_components/home\_keeper/options.py                       |      122 |        0 |       52 |        0 |    100% |           |
| custom\_components/home\_keeper/panel.py                         |       29 |        2 |        6 |        0 |     89% |   111-112 |
| custom\_components/home\_keeper/photo\_thumbs.py                 |       34 |        0 |        8 |        0 |    100% |           |
| custom\_components/home\_keeper/problem\_sync.py                 |      135 |       66 |       48 |        3 |     44% |68, 79-92, 96-98, 103-109, 121-157, 161-166, 177-184, 190, 202, 265-267, 272-275 |
| custom\_components/home\_keeper/problem\_tasks.py                |       76 |        0 |       30 |        0 |    100% |           |
| custom\_components/home\_keeper/profiles.py                      |      106 |        1 |       50 |        1 |     99% |       132 |
| custom\_components/home\_keeper/reconcile.py                     |      374 |        5 |      210 |        8 |     98% |190, 210, 316, 318, 319-\>322, 395, 790-\>798, 955-\>953 |
| custom\_components/home\_keeper/recurrence.py                    |      415 |        7 |      194 |        8 |     98% |244, 347, 359, 392, 493, 694, 1045-\>1047, 1131 |
| custom\_components/home\_keeper/resolve.py                       |       62 |        0 |       18 |        0 |    100% |           |
| custom\_components/home\_keeper/sensor.py                        |      169 |      109 |       42 |        0 |     28% |58, 63, 76-126, 141-165, 186-187, 191-192, 196-219, 230-265, 304-309, 323-326, 371-381, 384-388, 392-399 |
| custom\_components/home\_keeper/sensor\_tasks.py                 |      193 |        2 |       82 |        3 |     98% |147, 180-\>175, 207 |
| custom\_components/home\_keeper/sensor\_watcher.py               |      368 |       71 |      158 |       30 |     77% |96, 103, 143, 146, 198, 201, 209-211, 271-287, 302-310, 429, 490-493, 501, 538, 546, 572-573, 579, 585-\>exit, 630, 632-\>626, 634-\>exit, 691, 704, 707, 738-750, 758, 760, 768, 774, 776, 778, 780, 818-819, 838-839, 844-845, 934-935, 967-968 |
| custom\_components/home\_keeper/service\_device.py               |        5 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/service\_errors.py               |       44 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/shopping.py                      |      219 |        1 |       98 |        1 |     99% |       466 |
| custom\_components/home\_keeper/shopping\_sync.py                |      106 |       10 |       40 |        8 |     86% |90-93, 116, 141, 153, 194-\>184, 241, 243, 244-\>246, 253 |
| custom\_components/home\_keeper/store.py                         |     1264 |      396 |      568 |      101 |     65% |123, 183-184, 209-211, 229, 335, 345, 353-365, 377-380, 382, 389, 391, 401, 460, 464, 479-483, 508, 511, 525-543, 554-564, 573, 577, 602, 610-614, 661, 668, 692, 697, 699, 743, 745, 782-806, 837-857, 886, 907-911, 955, 956-\>965, 960-\>965, 969-\>971, 971-\>exit, 1081, 1109-1123, 1128, 1134, 1152, 1233-\>1221, 1246, 1258, 1259-\>1242, 1384-1395, 1408-1413, 1424-1436, 1448-1454, 1467-1473, 1484-1498, 1534, 1546, 1555-1557, 1574-1587, 1630-1639, 1652-1665, 1708, 1722, 1755-\>1765, 1759-\>1758, 1790-1793, 1874-\>1885, 1887, 1895-1896, 1899, 1910, 1916-1917, 1925, 1942-1948, 1952-1958, 1992-1993, 2002, 2006-\>2005, 2015, 2037-2066, 2091, 2116-2121, 2153, 2184, 2187-\>2162, 2197, 2200, 2217-2237, 2249-2281, 2295, 2302-\>2301, 2308-\>2307, 2312-\>2307, 2330-2342, 2399, 2416, 2421-\>2409, 2428-2434, 2438-2443, 2444-\>2409, 2458, 2496, 2506, 2518-2522, 2533-\>2536, 2590, 2601-2602, 2610, 2633-2647, 2670, 2681, 2695-2697, 2731, 2746-2747, 2748-\>2750, 2757, 2796, 2807-2808, 2814, 2829-2841, 2858-2885, 2898-2914, 2923-2936, 2957-2960, 2980, 2985, 2993, 2996, 3010-\>exit, 3012-\>3016, 3046, 3051-\>exit, 3098, 3123, 3126, 3129-\>exit, 3137-\>exit, 3176, 3179 |
| custom\_components/home\_keeper/tag\_listener.py                 |       38 |        4 |       12 |        2 |     88% |46-55, 57-\>exit, 77 |
| custom\_components/home\_keeper/tags.py                          |       11 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_counts.py                  |       20 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_entities.py                |       48 |        0 |       22 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_photos.py                  |       82 |        0 |       28 |        0 |    100% |           |
| custom\_components/home\_keeper/template\_context.py             |       50 |       10 |       18 |        4 |     74% |109, 149-151, 155-157, 160-162 |
| custom\_components/home\_keeper/todo.py                          |       75 |        4 |       22 |        0 |     96% |43-44, 164-165 |
| custom\_components/home\_keeper/todo\_items.py                   |       51 |        0 |       22 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list.py                    |      258 |        0 |      108 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list\_sync.py              |      143 |        2 |       56 |        2 |     98% |  200, 215 |
| custom\_components/home\_keeper/todo\_sync\_driver.py            |      109 |        3 |       26 |        2 |     96% |235-236, 297 |
| custom\_components/home\_keeper/transfer.py                      |      650 |        2 |      270 |        4 |     99% |633-\>651, 882, 901, 1600-\>1599 |
| custom\_components/home\_keeper/transfer\_runner.py              |       57 |        4 |       18 |        5 |     85% |105-\>132, 129-\>132, 134-\>174, 145-153, 174-\>180 |
| custom\_components/home\_keeper/transitions.py                   |       45 |        0 |       16 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py                |      633 |      633 |       82 |        0 |      0% |    8-1747 |
| **TOTAL**                                                        | **11318** | **2727** | **4080** |  **284** | **77%** |           |


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