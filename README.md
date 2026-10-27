# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                             |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py                  |      664 |      664 |       80 |        0 |      0% |    8-2278 |
| custom\_components/home\_keeper/api\_surface.py                  |      115 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/appliance\_report.py             |       68 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/assets.py                        |      732 |       19 |      320 |       18 |     96% |164, 197, 216, 221, 265, 289, 292, 295, 398-\>397, 451, 626, 629, 640, 676, 793, 1453, 1726-1727, 1751-1752, 1754-\>1767 |
| custom\_components/home\_keeper/backend\_i18n.py                 |       49 |        5 |        8 |        1 |     89% |76-77, 80, 108-109 |
| custom\_components/home\_keeper/binary\_sensor.py                |       69 |       69 |        6 |        0 |      0% |    12-151 |
| custom\_components/home\_keeper/button.py                        |       41 |       13 |        4 |        0 |     67% |39-61, 73-74 |
| custom\_components/home\_keeper/calendar.py                      |      116 |       10 |       50 |        7 |     90% |36-37, 144, 149-\>142, 162, 171, 199, 207, 212, 215-216, 222-\>205 |
| custom\_components/home\_keeper/card.py                          |       87 |        7 |       28 |        2 |     92% |87-89, 129-130, 134, 153 |
| custom\_components/home\_keeper/card\_resource.py                |       29 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/companions.py                    |       91 |       35 |       18 |        2 |     55% |62, 108, 138-\>140, 149, 165-169, 173, 189-212, 217-221, 227-229, 239, 245, 251, 257, 269-270 |
| custom\_components/home\_keeper/companions\_catalog.py           |       40 |        1 |       12 |        0 |     98% |        61 |
| custom\_components/home\_keeper/config\_flow.py                  |       30 |        7 |        4 |        1 |     71% |165-171, 177, 200 |
| custom\_components/home\_keeper/const.py                         |      229 |        1 |       12 |        1 |     99% |      1075 |
| custom\_components/home\_keeper/coordinator.py                   |      180 |       72 |       60 |        3 |     55% |116-121, 130-175, 204, 208, 254, 264, 266-\>exit, 280-283, 286-345, 397, 409, 419, 430, 443-453, 484-495 |
| custom\_components/home\_keeper/cost\_summary.py                 |       62 |        0 |       28 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_companion\_sync.py  |      236 |       94 |       52 |        1 |     60% |78-79, 122-162, 182-183, 240-245, 256-260, 270, 281-285, 289, 308, 339-343, 465-485, 493, 500, 507, 586, 592, 605-675, 690-697, 707-712 |
| custom\_components/home\_keeper/declarative\_companions.py       |      397 |        3 |      198 |        3 |     99% |136, 262, 264 |
| custom\_components/home\_keeper/declarative\_preset\_text.py     |        2 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_presets.py          |      161 |        0 |       60 |        0 |    100% |           |
| custom\_components/home\_keeper/declarative\_presets\_catalog.py |        3 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/device\_compat.py                |       52 |        0 |       20 |        0 |    100% |           |
| custom\_components/home\_keeper/device\_trigger.py               |       69 |       69 |       24 |        0 |      0% |    23-163 |
| custom\_components/home\_keeper/devices.py                       |      251 |       56 |      136 |       15 |     76% |71-73, 78, 87-90, 92, 102, 118-124, 161-\>146, 186-192, 269-\>276, 374, 420-430, 451-464, 533, 543, 550, 561-562, 569-\>572, 589-595, 603-604, 606-607, 635-\>exit, 669-677 |
| custom\_components/home\_keeper/diagnostics.py                   |       23 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/documents.py                     |       93 |        1 |       34 |        1 |     98% |       209 |
| custom\_components/home\_keeper/entity.py                        |       51 |       27 |        8 |        0 |     41% |51-70, 74, 95-103, 107-108, 116-117, 135-140 |
| custom\_components/home\_keeper/event.py                         |       43 |        0 |        6 |        0 |    100% |           |
| custom\_components/home\_keeper/events.py                        |       91 |        0 |       40 |        1 |     99% | 270-\>272 |
| custom\_components/home\_keeper/logbook.py                       |       22 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/manuals.py                       |      500 |      144 |      116 |       25 |     68% |144-145, 194-197, 220-226, 245, 288, 306-308, 334-\>exit, 379, 403-412, 417, 422, 443, 470-472, 495-498, 536-543, 557-562, 595-596, 611, 613-614, 616, 623-624, 630-632, 636-\>638, 641-643, 671-\>673, 674-675, 676-\>682, 705-723, 744-745, 748-749, 752-753, 781-\>exit, 799-804, 821, 826, 835-837, 857-862, 878-883, 888-899, 927-932, 947, 950-953, 957, 964-966, 968, 984-987, 1007-1018, 1059-1060, 1085-1086, 1103, 1114, 1171-1174, 1205-1210 |
| custom\_components/home\_keeper/models.py                        |      640 |        7 |      374 |        6 |     99% |238, 249, 614, 872-\>875, 921, 925, 1020-1021 |
| custom\_components/home\_keeper/notifications.py                 |      267 |        5 |       92 |        1 |     98% |365, 555-556, 564-565 |
| custom\_components/home\_keeper/notifier.py                      |      209 |       23 |       88 |       15 |     87% |61-62, 102-104, 108, 132, 142, 284, 374, 391, 438, 446, 453, 478, 493, 518-520, 552, 631-638, 655-\>exit, 671 |
| custom\_components/home\_keeper/number.py                        |       72 |       72 |       14 |        0 |      0% |    11-159 |
| custom\_components/home\_keeper/options.py                       |      159 |        0 |       72 |        0 |    100% |           |
| custom\_components/home\_keeper/panel.py                         |       29 |        2 |        6 |        0 |     89% |   110-111 |
| custom\_components/home\_keeper/panel\_tabs.py                   |      145 |        0 |       64 |        0 |    100% |           |
| custom\_components/home\_keeper/photo\_thumbs.py                 |       38 |        0 |        8 |        0 |    100% |           |
| custom\_components/home\_keeper/problem\_sync.py                 |      138 |       66 |       48 |        3 |     45% |68, 79-92, 96-98, 103-109, 121-158, 162-167, 190-197, 203, 215, 278-280, 285-288 |
| custom\_components/home\_keeper/problem\_tasks.py                |       76 |        0 |       30 |        0 |    100% |           |
| custom\_components/home\_keeper/profiles.py                      |      106 |        1 |       50 |        1 |     99% |       132 |
| custom\_components/home\_keeper/reconcile.py                     |      374 |        5 |      210 |        8 |     98% |190, 210, 316, 318, 319-\>322, 395, 790-\>798, 955-\>953 |
| custom\_components/home\_keeper/recurrence.py                    |      668 |        6 |      300 |        7 |     99% |385, 578-579, 634-\>643, 785-\>797, 1010, 1193, 1583-\>1585, 1669 |
| custom\_components/home\_keeper/resolve.py                       |       62 |        0 |       18 |        0 |    100% |           |
| custom\_components/home\_keeper/sensor.py                        |      234 |      115 |       48 |        0 |     44% |73, 78, 91-144, 181-205, 226-227, 231-232, 236-259, 270-305, 344-349, 363-366, 411-421, 424-428, 432-439, 462, 466-467 |
| custom\_components/home\_keeper/sensor\_tasks.py                 |      193 |        2 |       82 |        3 |     98% |147, 180-\>175, 207 |
| custom\_components/home\_keeper/sensor\_watcher.py               |      368 |       71 |      158 |       30 |     77% |96, 103, 143, 146, 198, 201, 209-211, 271-287, 302-310, 429, 490-493, 501, 538, 546, 572-573, 579, 585-\>exit, 630, 632-\>626, 634-\>exit, 691, 704, 707, 738-750, 758, 760, 768, 774, 776, 778, 780, 818-819, 838-839, 844-845, 934-935, 967-968 |
| custom\_components/home\_keeper/service\_device.py               |        5 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/service\_errors.py               |       44 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/shopping.py                      |      226 |        1 |      104 |        1 |     99% |       487 |
| custom\_components/home\_keeper/shopping\_sync.py                |      106 |       10 |       40 |        8 |     86% |90-93, 116, 141, 153, 194-\>184, 241, 243, 244-\>246, 253 |
| custom\_components/home\_keeper/store.py                         |     1335 |      336 |      602 |      109 |     71% |128, 202-203, 226, 262, 387, 407-416, 429-432, 434, 446, 448, 540, 544, 559-563, 588, 591, 607-613, 640-645, 654, 659, 686, 694-698, 745, 752, 776, 781, 783, 827, 829, 866, 871, 982, 987, 1029, 1050-1054, 1098, 1099-\>1108, 1103-\>1108, 1112-\>1114, 1114-\>exit, 1224, 1252-1266, 1271, 1277, 1295, 1376-\>1364, 1389, 1401, 1402-\>1385, 1533-1544, 1557-1562, 1573-1585, 1597-1603, 1616-1622, 1633-1647, 1683, 1695, 1704-1706, 1736, 1737-\>1734, 1740-\>1734, 1794-1803, 1884, 1898, 1931-\>1941, 1935-\>1934, 1966-1969, 2050-\>2061, 2063, 2071-2072, 2075, 2086, 2092-2093, 2101, 2118-2124, 2128-2134, 2166, 2174-2175, 2184, 2188-\>2187, 2197, 2219-2248, 2273, 2298-2303, 2335, 2366, 2369-\>2344, 2379, 2382, 2399-2419, 2431-2463, 2477, 2484-\>2483, 2490-\>2489, 2494-\>2489, 2512-2524, 2581, 2598, 2603-\>2591, 2610-2616, 2620-2625, 2626-\>2591, 2640, 2678, 2688, 2700-2704, 2719-\>2722, 2774, 2785-2786, 2794, 2817-2831, 2854, 2865, 2881-2883, 2917, 2932-2933, 2934-\>2936, 2943, 2982, 2993-2994, 3000, 3015-3027, 3044-3071, 3084-3100, 3109-3122, 3143-3146, 3166, 3171, 3179, 3182, 3196-\>exit, 3198-\>3202, 3232, 3237-\>exit, 3284, 3309, 3312, 3315-\>exit, 3323-\>exit, 3362, 3365 |
| custom\_components/home\_keeper/tag\_listener.py                 |       38 |        4 |       12 |        2 |     88% |46-55, 57-\>exit, 77 |
| custom\_components/home\_keeper/tags.py                          |       11 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_counts.py                  |       20 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_entities.py                |       48 |        0 |       22 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_photos.py                  |       92 |        0 |       32 |        0 |    100% |           |
| custom\_components/home\_keeper/template\_context.py             |       50 |       10 |       18 |        4 |     74% |109, 149-151, 155-157, 160-162 |
| custom\_components/home\_keeper/todo.py                          |       78 |        6 |       22 |        0 |     94% |43-44, 71-72, 173-174 |
| custom\_components/home\_keeper/todo\_items.py                   |       51 |        0 |       22 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list.py                    |      269 |        0 |      112 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list\_sync.py              |      143 |        2 |       56 |        2 |     98% |  200, 215 |
| custom\_components/home\_keeper/todo\_sync\_driver.py            |      109 |        3 |       26 |        2 |     96% |235-236, 297 |
| custom\_components/home\_keeper/transfer.py                      |      732 |        2 |      296 |        3 |     99% |891, 910, 1617-\>1616 |
| custom\_components/home\_keeper/transfer\_bundle.py              |      365 |        7 |      162 |        9 |     97% |136-\>128, 144, 183, 211, 311-312, 338, 341-\>340, 605-\>607, 745-\>776, 822 |
| custom\_components/home\_keeper/transfer\_http.py                |      179 |       16 |       44 |        3 |     91% |56-58, 209-210, 226, 235, 240-241, 312-313, 320-325 |
| custom\_components/home\_keeper/transfer\_runner.py              |      438 |       42 |      128 |       10 |     90% |95, 103-105, 146, 192, 203, 335-336, 408-410, 423, 464, 499-501, 510, 527, 529-\>533, 565-567, 606-608, 622-624, 644-646, 654-655, 674-681, 730-\>733, 744-751, 984-985 |
| custom\_components/home\_keeper/transitions.py                   |       45 |        0 |       16 |        0 |    100% |           |
| custom\_components/home\_keeper/trigger.py                       |       58 |       58 |        8 |        0 |      0% |    21-143 |
| custom\_components/home\_keeper/trigger\_targets.py              |       47 |        0 |       12 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py                |      708 |      708 |      100 |        0 |      0% |    8-1960 |
| **TOTAL**                                                        | **13571** | **2877** | **4854** |  **308** | **80%** |           |


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