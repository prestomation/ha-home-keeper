# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                             |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py                  |      622 |      622 |       76 |        0 |      0% |    8-2116 |
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
| custom\_components/home\_keeper/const.py                         |      194 |        1 |       12 |        1 |     99% |       975 |
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
| custom\_components/home\_keeper/manuals.py                       |      344 |      124 |       74 |       22 |     60% |131-132, 181-184, 207-213, 232, 264, 269, 274, 295, 322-324, 347-350, 388-395, 409-414, 448-449, 464, 466-467, 469, 476-477, 480, 483-485, 489-\>491, 494-496, 521-522, 524-\>526, 527-528, 529-\>535, 558-576, 597-598, 601-602, 605-606, 634-\>exit, 652-657, 674, 679, 688-690, 710-715, 731-736, 741-752, 780-785, 800, 803-806, 810, 817-819, 821, 837-840, 860-871, 880-884 |
| custom\_components/home\_keeper/models.py                        |      528 |        8 |      324 |        6 |     98% |224, 235, 600, 743, 747, 841, 845-846 |
| custom\_components/home\_keeper/notifications.py                 |      267 |        5 |       92 |        1 |     98% |365, 555-556, 564-565 |
| custom\_components/home\_keeper/notifier.py                      |      209 |       23 |       88 |       15 |     87% |61-62, 102-104, 108, 132, 142, 284, 374, 391, 438, 446, 453, 478, 493, 518-520, 552, 631-638, 655-\>exit, 671 |
| custom\_components/home\_keeper/number.py                        |       72 |       72 |       14 |        0 |      0% |    11-159 |
| custom\_components/home\_keeper/options.py                       |      122 |        0 |       52 |        0 |    100% |           |
| custom\_components/home\_keeper/panel.py                         |       29 |        2 |        6 |        0 |     89% |   111-112 |
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
| custom\_components/home\_keeper/service\_errors.py               |       42 |        0 |       12 |        0 |    100% |           |
| custom\_components/home\_keeper/shopping.py                      |      219 |        1 |       98 |        1 |     99% |       466 |
| custom\_components/home\_keeper/shopping\_sync.py                |      106 |       10 |       40 |        8 |     86% |90-93, 116, 141, 153, 194-\>184, 241, 243, 244-\>246, 253 |
| custom\_components/home\_keeper/store.py                         |     1228 |      396 |      560 |      101 |     64% |122, 182-183, 208-210, 228, 330, 340, 348-360, 372-375, 377, 384, 386, 395, 439, 443, 458-462, 487, 490, 504-522, 533-543, 552, 556, 581, 589-593, 640, 647, 671, 676, 678, 722, 724, 761-785, 816-836, 865, 886-890, 934, 935-\>944, 939-\>944, 948-\>950, 950-\>exit, 1060, 1088-1102, 1107, 1113, 1131, 1212-\>1200, 1225, 1237, 1238-\>1221, 1295-1306, 1319-1324, 1335-1347, 1359-1365, 1378-1384, 1395-1409, 1445, 1457, 1466-1468, 1485-1498, 1541-1550, 1563-1576, 1619, 1633, 1666-\>1676, 1670-\>1669, 1701-1704, 1785-\>1796, 1798, 1806-1807, 1810, 1821, 1827-1828, 1836, 1853-1859, 1863-1869, 1903-1904, 1913, 1917-\>1916, 1926, 1948-1977, 2002, 2027-2032, 2064, 2095, 2098-\>2073, 2108, 2111, 2128-2148, 2160-2192, 2206, 2213-\>2212, 2219-\>2218, 2223-\>2218, 2241-2253, 2310, 2327, 2332-\>2320, 2339-2345, 2349-2354, 2355-\>2320, 2369, 2407, 2417, 2429-2433, 2444-\>2447, 2501, 2512-2513, 2521, 2544-2558, 2581, 2592, 2606-2608, 2642, 2657-2658, 2659-\>2661, 2668, 2707, 2718-2719, 2725, 2740-2752, 2769-2796, 2809-2825, 2834-2847, 2868-2871, 2891, 2896, 2904, 2907, 2921-\>exit, 2923-\>2927, 2957, 2962-\>exit, 3009, 3034, 3037, 3040-\>exit, 3048-\>exit, 3087, 3090 |
| custom\_components/home\_keeper/tag\_listener.py                 |       38 |        4 |       12 |        2 |     88% |46-55, 57-\>exit, 77 |
| custom\_components/home\_keeper/tags.py                          |       11 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_counts.py                  |       20 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_entities.py                |       48 |        0 |       22 |        0 |    100% |           |
| custom\_components/home\_keeper/template\_context.py             |       50 |       10 |       18 |        4 |     74% |109, 149-151, 155-157, 160-162 |
| custom\_components/home\_keeper/todo.py                          |       75 |        4 |       22 |        0 |     96% |43-44, 164-165 |
| custom\_components/home\_keeper/todo\_items.py                   |       51 |        0 |       22 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list.py                    |      258 |        0 |      108 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list\_sync.py              |      143 |        2 |       56 |        2 |     98% |  200, 215 |
| custom\_components/home\_keeper/todo\_sync\_driver.py            |      109 |        3 |       26 |        2 |     96% |235-236, 297 |
| custom\_components/home\_keeper/transfer.py                      |      646 |        2 |      268 |        4 |     99% |617-\>633, 864, 883, 1582-\>1581 |
| custom\_components/home\_keeper/transfer\_runner.py              |       57 |        4 |       18 |        5 |     85% |105-\>132, 129-\>132, 134-\>174, 145-153, 174-\>180 |
| custom\_components/home\_keeper/transitions.py                   |       45 |        0 |       16 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py                |      605 |      605 |       80 |        0 |      0% |    8-1634 |
| **TOTAL**                                                        | **10978** | **2654** | **4000** |  **282** | **77%** |           |


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