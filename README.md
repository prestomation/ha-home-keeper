# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/prestomation/ha-home-keeper/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                             |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/home\_keeper/\_\_init\_\_.py                  |      666 |      666 |       82 |        0 |      0% |    8-2287 |
| custom\_components/home\_keeper/api\_surface.py                  |      115 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/appliance\_report.py             |       68 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/assets.py                        |      732 |       19 |      320 |       18 |     96% |164, 197, 216, 221, 265, 289, 292, 295, 398-\>397, 451, 626, 629, 640, 676, 793, 1453, 1726-1727, 1751-1752, 1754-\>1767 |
| custom\_components/home\_keeper/backend\_i18n.py                 |       49 |        5 |        8 |        1 |     89% |76-77, 80, 108-109 |
| custom\_components/home\_keeper/binary\_sensor.py                |       70 |       70 |        6 |        0 |      0% |    12-152 |
| custom\_components/home\_keeper/button.py                        |       41 |       13 |        4 |        0 |     67% |43-65, 77-78 |
| custom\_components/home\_keeper/calendar.py                      |      116 |       10 |       50 |        7 |     90% |36-37, 144, 149-\>142, 162, 171, 199, 207, 212, 215-216, 222-\>205 |
| custom\_components/home\_keeper/card.py                          |       87 |        7 |       28 |        2 |     92% |87-89, 129-130, 134, 153 |
| custom\_components/home\_keeper/card\_resource.py                |       29 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/companions.py                    |       91 |       35 |       18 |        2 |     55% |62, 108, 138-\>140, 149, 165-169, 173, 189-212, 217-221, 227-229, 239, 245, 251, 257, 269-270 |
| custom\_components/home\_keeper/companions\_catalog.py           |       40 |        1 |       12 |        0 |     98% |        61 |
| custom\_components/home\_keeper/config\_flow.py                  |       30 |        7 |        4 |        1 |     71% |165-171, 177, 200 |
| custom\_components/home\_keeper/const.py                         |      230 |        1 |       12 |        1 |     99% |      1079 |
| custom\_components/home\_keeper/coordinator.py                   |      231 |       75 |       86 |        4 |     65% |133-138, 147-197, 226, 230, 276, 286, 288-\>exit, 352, 386-389, 392-451, 503, 511, 521, 532, 545-555, 586-597 |
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
| custom\_components/home\_keeper/entity.py                        |       52 |       28 |        8 |        0 |     40% |51-74, 80, 101-109, 113-114, 122-123, 141-146 |
| custom\_components/home\_keeper/event.py                         |       43 |        0 |        6 |        0 |    100% |           |
| custom\_components/home\_keeper/events.py                        |       91 |        0 |       40 |        1 |     99% | 270-\>272 |
| custom\_components/home\_keeper/logbook.py                       |       22 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/manuals.py                       |      500 |      144 |      116 |       25 |     68% |144-145, 194-197, 220-226, 246, 289, 307-309, 335-\>exit, 380, 404-413, 418, 423, 444, 471-473, 496-499, 537-544, 558-563, 596-597, 612, 614-615, 617, 624-625, 631-633, 637-\>639, 642-644, 672-\>674, 675-676, 677-\>683, 706-724, 745-746, 749-750, 753-754, 782-\>exit, 800-805, 822, 827, 836-838, 858-863, 879-884, 889-900, 928-933, 948, 951-954, 958, 965-967, 969, 985-988, 1008-1019, 1060-1061, 1086-1087, 1104, 1115, 1172-1175, 1206-1211 |
| custom\_components/home\_keeper/models.py                        |      640 |        7 |      374 |        6 |     99% |238, 249, 614, 872-\>875, 921, 925, 1020-1021 |
| custom\_components/home\_keeper/notifications.py                 |      267 |        5 |       92 |        1 |     98% |365, 555-556, 564-565 |
| custom\_components/home\_keeper/notifier.py                      |      209 |       23 |       88 |       15 |     87% |61-62, 102-104, 108, 132, 142, 284, 374, 391, 438, 446, 453, 478, 493, 518-520, 552, 631-638, 655-\>exit, 671 |
| custom\_components/home\_keeper/number.py                        |       72 |       72 |       14 |        0 |      0% |    11-159 |
| custom\_components/home\_keeper/options.py                       |      175 |        0 |       74 |        0 |    100% |           |
| custom\_components/home\_keeper/panel.py                         |       29 |        2 |        6 |        0 |     89% |   110-111 |
| custom\_components/home\_keeper/panel\_tabs.py                   |      145 |        0 |       64 |        0 |    100% |           |
| custom\_components/home\_keeper/photo\_thumbs.py                 |       38 |        0 |        8 |        0 |    100% |           |
| custom\_components/home\_keeper/problem\_sync.py                 |      141 |       66 |       48 |        3 |     46% |68, 90-103, 107-109, 114-120, 132-169, 173-178, 201-208, 214, 226, 289-291, 296-299 |
| custom\_components/home\_keeper/problem\_tasks.py                |       77 |        0 |       30 |        0 |    100% |           |
| custom\_components/home\_keeper/profiles.py                      |      106 |        1 |       50 |        1 |     99% |       132 |
| custom\_components/home\_keeper/reconcile.py                     |      374 |        5 |      210 |        7 |     98% |190, 210, 316, 318, 319-\>322, 395, 790-\>798 |
| custom\_components/home\_keeper/recurrence.py                    |      668 |        6 |      300 |        7 |     99% |385, 578-579, 634-\>643, 785-\>797, 1010, 1193, 1583-\>1585, 1669 |
| custom\_components/home\_keeper/resolve.py                       |       62 |        0 |       18 |        0 |    100% |           |
| custom\_components/home\_keeper/sensor.py                        |      243 |      109 |       54 |        0 |     48% |74, 79, 92-145, 182-207, 228-229, 233-234, 238-261, 272-307, 384-387, 432-442, 445-449, 453-460, 483, 487-488 |
| custom\_components/home\_keeper/sensor\_tasks.py                 |      193 |        2 |       82 |        3 |     98% |147, 180-\>175, 207 |
| custom\_components/home\_keeper/sensor\_watcher.py               |      368 |       71 |      158 |       30 |     77% |96, 103, 143, 146, 198, 201, 209-211, 271-287, 302-310, 429, 490-493, 501, 538, 546, 572-573, 579, 585-\>exit, 630, 632-\>626, 634-\>exit, 691, 704, 707, 738-750, 758, 760, 768, 774, 776, 778, 780, 818-819, 838-839, 844-845, 934-935, 967-968 |
| custom\_components/home\_keeper/service\_device.py               |        5 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/service\_errors.py               |       44 |        0 |       14 |        0 |    100% |           |
| custom\_components/home\_keeper/shopping.py                      |      225 |        1 |      104 |        1 |     99% |       492 |
| custom\_components/home\_keeper/shopping\_sync.py                |      111 |        6 |       38 |        8 |     91% |119, 144, 156, 197-\>187, 244, 246, 247-\>249, 256 |
| custom\_components/home\_keeper/store.py                         |     1335 |      333 |      606 |      110 |     71% |128, 181-182, 205, 241, 367, 387-396, 409-412, 414, 426, 428, 520, 524, 539-543, 568, 571, 587-593, 620-625, 634, 639, 666, 678, 730, 737, 761, 766, 768, 812, 814, 851, 856, 967, 972, 1014, 1035-1039, 1083, 1084-\>1093, 1088-\>1093, 1097-\>1099, 1099-\>exit, 1209, 1237-1251, 1256, 1262, 1280, 1311-\>1316, 1365-\>1353, 1378, 1390, 1391-\>1374, 1522-1533, 1546-1551, 1562-1574, 1586-1592, 1605-1611, 1622-1636, 1672, 1684, 1693-1695, 1725, 1726-\>1723, 1729-\>1723, 1783-1792, 1873, 1887, 1920-\>1930, 1924-\>1923, 1955-1958, 2039-\>2050, 2052, 2060-2061, 2064, 2075, 2081-2082, 2090, 2107-2113, 2117-2123, 2155, 2163-2164, 2173, 2177-\>2176, 2186, 2208-2237, 2262, 2287-2292, 2324, 2355, 2358-\>2333, 2368, 2371, 2388-2408, 2420-2452, 2466, 2473-\>2472, 2479-\>2478, 2483-\>2478, 2501-2513, 2570, 2587, 2592-\>2580, 2599-2605, 2609-2614, 2615-\>2580, 2629, 2667, 2677, 2689-2693, 2708-\>2711, 2763, 2774-2775, 2783, 2806-2820, 2843, 2854, 2870-2872, 2906, 2921-2922, 2923-\>2925, 2932, 2971, 2982-2983, 2989, 3004-3016, 3033-3060, 3073-3089, 3098-3111, 3132-3135, 3155, 3160, 3168, 3171, 3185-\>exit, 3187-\>3191, 3221, 3226-\>exit, 3273, 3298, 3301, 3304-\>exit, 3312-\>exit, 3351, 3354 |
| custom\_components/home\_keeper/tag\_listener.py                 |       38 |        4 |       12 |        2 |     88% |46-55, 57-\>exit, 77 |
| custom\_components/home\_keeper/tags.py                          |       11 |        0 |        2 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_counts.py                  |       20 |        0 |        0 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_entities.py                |       68 |        0 |       26 |        0 |    100% |           |
| custom\_components/home\_keeper/task\_photos.py                  |       92 |        0 |       32 |        0 |    100% |           |
| custom\_components/home\_keeper/template\_context.py             |       50 |       10 |       18 |        4 |     74% |109, 149-151, 155-157, 160-162 |
| custom\_components/home\_keeper/todo.py                          |       77 |        6 |       22 |        0 |     94% |43-44, 71-72, 172-173 |
| custom\_components/home\_keeper/todo\_items.py                   |       53 |        0 |       16 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list.py                    |      278 |        0 |      114 |        0 |    100% |           |
| custom\_components/home\_keeper/todo\_list\_sync.py              |      147 |        2 |       54 |        2 |     98% |  199, 214 |
| custom\_components/home\_keeper/todo\_sync\_driver.py            |      135 |        3 |       34 |        2 |     97% |282-283, 344 |
| custom\_components/home\_keeper/transfer.py                      |      732 |        2 |      296 |        3 |     99% |891, 910, 1617-\>1616 |
| custom\_components/home\_keeper/transfer\_bundle.py              |      365 |        7 |      162 |        9 |     97% |136-\>128, 144, 183, 211, 311-312, 338, 341-\>340, 605-\>607, 745-\>776, 822 |
| custom\_components/home\_keeper/transfer\_http.py                |      179 |       16 |       44 |        3 |     91% |56-58, 209-210, 226, 235, 240-241, 312-313, 320-325 |
| custom\_components/home\_keeper/transfer\_runner.py              |      438 |       42 |      128 |       10 |     90% |95, 103-105, 146, 192, 203, 335-336, 408-410, 423, 464, 499-501, 510, 527, 529-\>533, 565-567, 606-608, 622-624, 644-646, 654-655, 674-681, 730-\>733, 744-751, 984-985 |
| custom\_components/home\_keeper/transitions.py                   |       47 |        0 |       18 |        0 |    100% |           |
| custom\_components/home\_keeper/trigger.py                       |       58 |       58 |        8 |        0 |      0% |    21-143 |
| custom\_components/home\_keeper/trigger\_targets.py              |       47 |        0 |       12 |        0 |    100% |           |
| custom\_components/home\_keeper/websocket\_api.py                |      710 |      710 |      102 |        0 |      0% |    8-1964 |
| **TOTAL**                                                        | **13724** | **2873** | **4902** |  **309** | **80%** |           |


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