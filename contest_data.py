"""Contest moves as the Generation 3 games judge them (8 November 2026; docs/CONTEST.md), from pret's
pokeemerald (src/data/contest_moves.h, include/constants/contest.h, include/constants/moves.h).

CONTEST_MOVES[move] = (category, appeal, jam, combo starter, combo moves, effect): the category is 0
cool, 1 beauty, 2 cute, 3 smart, 4 tough; appeal and jam are the effect's points (ten to a heart);
a move whose combo moves include the previous move's combo starter makes a combo
(AreMovesContestCombo), worth its appeal again if the judge noticed the starter."""

CONTEST_MOVES = {
    1: (4, 40, 0, 60, (), 'highly_appealing'),
    2: (4, 30, 0, 0, (3,), 'affected_by_prev_appeal'),
    3: (4, 20, 10, 0, (60,), 'startle_mon_with_judges_attention'),
    4: (4, 20, 0, 0, (), 'better_if_same_type'),
    5: (4, 40, 0, 0, (3, 26), 'highly_appealing'),
    6: (3, 10, 0, 0, (), 'better_when_audience_excited'),
    7: (1, 40, 0, 45, (9, 44, 46), 'highly_appealing'),
    8: (1, 40, 0, 46, (44, 45), 'highly_appealing'),
    9: (0, 40, 0, 44, (13, 45, 46), 'highly_appealing'),
    10: (4, 40, 0, 21, (33,), 'highly_appealing'),
    11: (4, 40, 0, 11, (), 'highly_appealing'),
    12: (0, 20, 10, 0, (11,), 'badly_startle_mons_with_good_appeals'),
    13: (0, 30, 0, 0, (), 'affected_by_prev_appeal'),
    14: (1, 10, 0, 7, (), 'improve_condition_prevent_nervousness'),
    15: (0, 20, 10, 0, (7,), 'badly_startle_mons_with_good_appeals'),
    16: (3, 30, 0, 0, (), 'scramble_next_turn_order'),
    17: (0, 20, 0, 0, (), 'better_if_same_type'),
    18: (3, 30, 0, 0, (), 'scramble_next_turn_order'),
    19: (3, 10, 0, 0, (), 'avoid_startle'),
    20: (4, 30, 0, 0, (11,), 'dont_excite_audience'),
    21: (4, 20, 10, 0, (60,), 'startle_mons_same_type_appeal'),
    22: (0, 40, 0, 0, (22,), 'highly_appealing'),
    23: (4, 10, 40, 0, (), 'badly_startle_front_mon'),
    24: (0, 20, 0, 0, (), 'better_if_same_type'),
    25: (0, 40, 0, 0, (3, 26), 'highly_appealing'),
    26: (0, 60, 0, 0, (26,), 'user_more_easily_startled'),
    27: (0, 10, 30, 0, (), 'badly_startle_prev_mons'),
    28: (2, 20, 10, 54, (55, 24), 'startle_mon_with_judges_attention'),
    29: (4, 20, 30, 0, (3,), 'startle_prev_mon'),
    30: (0, 40, 0, 6, (33,), 'highly_appealing'),
    31: (0, 20, 10, 0, (6, 47), 'startle_mon_with_judges_attention'),
    32: (0, 20, 10, 0, (6,), 'badly_startle_mons_with_good_appeals'),
    33: (4, 40, 0, 0, (12, 33, 36), 'highly_appealing'),
    34: (4, 10, 40, 0, (), 'badly_startle_front_mon'),
    35: (4, 30, 0, 0, (), 'dont_excite_audience'),
    36: (4, 60, 0, 0, (3, 36), 'user_more_easily_startled'),
    37: (4, 40, 40, 0, (2,), 'jams_others_but_miss_one_turn'),
    38: (4, 60, 0, 0, (3, 36), 'user_more_easily_startled'),
    39: (2, 20, 0, 0, (35,), 'better_if_last'),
    40: (3, 20, 30, 0, (), 'startle_prev_mon'),
    41: (0, 20, 30, 0, (), 'startle_prev_mon'),
    42: (0, 20, 10, 0, (), 'startle_mon_with_judges_attention'),
    43: (0, 30, 0, 33, (2, 16), 'dont_excite_audience'),
    44: (4, 10, 30, 0, (33, 16), 'badly_startle_prev_mons'),
    45: (2, 20, 0, 0, (35,), 'better_if_last'),
    46: (0, 30, 0, 0, (), 'scramble_next_turn_order'),
    47: (2, 20, 0, 37, (), 'make_following_mons_nervous'),
    48: (3, 30, 0, 0, (), 'scramble_next_turn_order'),
    49: (0, 20, 0, 0, (), 'better_if_same_type'),
    50: (3, 20, 0, 0, (), 'make_following_mons_nervous'),
    51: (3, 10, 40, 0, (), 'badly_startle_front_mon'),
    52: (1, 40, 0, 0, (9,), 'highly_appealing'),
    53: (1, 40, 0, 0, (9,), 'highly_appealing'),
    54: (1, 10, 0, 0, (), 'avoid_startle'),
    55: (2, 40, 0, 0, (1, 50, 49), 'highly_appealing'),
    56: (1, 40, 0, 0, (1,), 'highly_appealing'),
    57: (1, 30, 0, 30, (1, 31), 'affected_by_prev_appeal'),
    58: (1, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    59: (1, 40, 0, 0, (17, 23), 'highly_appealing'),
    60: (1, 30, 0, 0, (62,), 'scramble_next_turn_order'),
    61: (1, 10, 30, 0, (1,), 'badly_startle_prev_mons'),
    62: (1, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    63: (0, 40, 40, 0, (), 'jams_others_but_miss_one_turn'),
    64: (0, 40, 0, 47, (), 'highly_appealing'),
    65: (0, 40, 0, 0, (47,), 'highly_appealing'),
    66: (0, 60, 0, 0, (26,), 'user_more_easily_startled'),
    67: (4, 10, 40, 0, (), 'badly_startle_front_mon'),
    68: (4, 20, 0, 0, (34,), 'avoid_startle_once'),
    69: (4, 20, 10, 0, (56,), 'startle_mons_same_type_appeal'),
    70: (4, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    71: (3, 20, 30, 0, (22,), 'startle_prev_mon'),
    72: (3, 10, 40, 0, (22,), 'badly_startle_front_mon'),
    73: (3, 20, 20, 0, (), 'startle_prev_mons'),
    74: (1, 10, 0, 22, (), 'improve_condition_prevent_nervousness'),
    75: (0, 30, 0, 0, (22,), 'affected_by_prev_appeal'),
    76: (0, 40, 0, 0, (9, 22), 'highly_appealing'),
    77: (3, 30, 0, 0, (41,), 'worsen_condition_of_prev_mons'),
    78: (3, 20, 10, 0, (41,), 'badly_startle_mons_with_good_appeals'),
    79: (3, 10, 30, 0, (41,), 'badly_startle_prev_mons'),
    80: (1, 40, 40, 0, (22,), 'jams_others_but_miss_one_turn'),
    81: (3, 20, 30, 32, (), 'startle_prev_mon'),
    82: (0, 10, 0, 28, (27, 29), 'better_when_later'),
    83: (1, 30, 0, 0, (9,), 'dont_excite_audience'),
    84: (0, 40, 0, 0, (13,), 'highly_appealing'),
    85: (0, 40, 0, 0, (13,), 'highly_appealing'),
    86: (0, 20, 10, 0, (13,), 'badly_startle_mons_with_good_appeals'),
    87: (0, 20, 20, 0, (13, 1, 18), 'startle_prev_mons'),
    88: (4, 20, 0, 14, (), 'better_if_same_type'),
    89: (4, 10, 30, 38, (), 'badly_startle_prev_mons'),
    90: (4, 20, 10, 0, (38,), 'badly_startle_mons_with_good_appeals'),
    91: (3, 10, 0, 0, (), 'avoid_startle'),
    92: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    93: (3, 20, 30, 59, (57, 58, 62), 'startle_prev_mon'),
    94: (3, 10, 30, 57, (58, 59, 62), 'badly_startle_prev_mons'),
    95: (3, 10, 30, 4, (), 'badly_startle_prev_mons'),
    96: (1, 10, 0, 0, (62,), 'improve_condition_prevent_nervousness'),
    97: (0, 30, 0, 0, (39,), 'next_appeal_earlier'),
    98: (0, 30, 0, 0, (39,), 'next_appeal_earlier'),
    99: (0, 30, 0, 2, (), 'repetition_not_boring'),
    100: (0, 10, 0, 0, (39, 57, 58, 59), 'avoid_startle'),
    101: (3, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    102: (2, 10, 0, 0, (), 'appeal_as_good_as_prev_one'),
    103: (3, 10, 30, 0, (), 'badly_startle_prev_mons'),
    104: (0, 20, 0, 39, (), 'avoid_startle_once'),
    105: (3, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    106: (4, 20, 0, 36, (), 'avoid_startle_once'),
    107: (2, 20, 0, 0, (), 'avoid_startle_once'),
    108: (3, 30, 0, 0, (61,), 'shift_judge_attention'),
    109: (3, 30, 0, 0, (), 'scramble_next_turn_order'),
    110: (2, 10, 0, 0, (1,), 'avoid_startle'),
    111: (2, 20, 0, 12, (), 'avoid_startle_once'),
    112: (0, 10, 0, 0, (), 'avoid_startle'),
    113: (1, 10, 0, 0, (62,), 'avoid_startle'),
    114: (1, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    115: (3, 10, 0, 0, (62,), 'avoid_startle'),
    116: (0, 10, 30, 3, (), 'badly_startle_prev_mons'),
    117: (4, 10, 0, 0, (), 'avoid_startle'),
    118: (2, 30, 0, 0, (), 'repetition_not_boring'),
    119: (3, 10, 0, 0, (), 'appeal_as_good_as_prev_one'),
    120: (1, 80, 0, 0, (), 'great_appeal_but_no_more_moves'),
    121: (4, 40, 0, 0, (19,), 'highly_appealing'),
    122: (4, 10, 40, 0, (), 'badly_startle_front_mon'),
    123: (4, 10, 30, 61, (), 'badly_startle_prev_mons'),
    124: (4, 10, 40, 42, (43,), 'badly_startle_front_mon'),
    125: (4, 20, 10, 51, (52, 53), 'startle_mon_with_judges_attention'),
    126: (1, 40, 0, 0, (9,), 'highly_appealing'),
    127: (4, 20, 0, 0, (1,), 'better_if_last'),
    128: (4, 30, 0, 0, (1,), 'dont_excite_audience'),
    129: (0, 20, 0, 0, (), 'better_if_first'),
    130: (4, 10, 40, 0, (), 'badly_startle_front_mon'),
    131: (0, 20, 10, 0, (), 'startle_mon_with_judges_attention'),
    132: (4, 20, 30, 0, (), 'startle_prev_mon'),
    133: (2, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    134: (3, 30, 0, 58, (57, 59), 'dont_excite_audience'),
    135: (1, 40, 0, 19, (), 'highly_appealing'),
    136: (0, 60, 0, 0, (26,), 'user_more_easily_startled'),
    137: (4, 10, 30, 0, (33,), 'badly_startle_prev_mons'),
    138: (3, 20, 20, 0, (4, 62), 'startle_prev_mons'),
    139: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    140: (4, 20, 0, 0, (), 'better_if_same_type'),
    141: (3, 20, 30, 0, (), 'startle_prev_mon'),
    142: (1, 10, 30, 0, (), 'badly_startle_prev_mons'),
    143: (0, 30, 0, 0, (), 'affected_by_prev_appeal'),
    144: (3, 30, 0, 0, (), 'repetition_not_boring'),
    145: (2, 20, 20, 0, (1,), 'startle_prev_mons'),
    146: (0, 10, 40, 0, (), 'badly_startle_front_mon'),
    147: (1, 10, 30, 0, (), 'badly_startle_prev_mons'),
    148: (1, 30, 0, 0, (), 'shift_judge_attention'),
    149: (3, 20, 10, 0, (62,), 'badly_startle_mons_with_good_appeals'),
    150: (2, 20, 0, 0, (), 'better_if_last'),
    151: (4, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    152: (4, 30, 0, 0, (1, 7), 'affected_by_prev_appeal'),
    153: (1, 80, 0, 0, (), 'great_appeal_but_no_more_moves'),
    154: (4, 20, 10, 0, (21,), 'startle_mon_with_judges_attention'),
    155: (4, 40, 0, 52, (51, 53), 'highly_appealing'),
    156: (2, 20, 0, 10, (25, 35, 15), 'avoid_startle_once'),
    157: (4, 10, 30, 0, (14,), 'badly_startle_prev_mons'),
    158: (0, 10, 40, 0, (), 'badly_startle_front_mon'),
    159: (2, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    160: (1, 20, 0, 0, (), 'better_if_same_type'),
    161: (1, 20, 20, 0, (18,), 'startle_prev_mons'),
    162: (4, 20, 10, 0, (16,), 'badly_startle_mons_with_good_appeals'),
    163: (0, 30, 0, 0, (7, 21), 'affected_by_prev_appeal'),
    164: (3, 20, 0, 0, (), 'avoid_startle_once'),
    165: (0, 40, 0, 0, (), 'highly_appealing'),
    166: (3, 10, 0, 0, (), 'appeal_as_good_as_prev_one'),
    167: (0, 40, 0, 0, (3,), 'highly_appealing'),
    168: (4, 10, 0, 0, (), 'appeal_as_good_as_prev_ones'),
    169: (3, 20, 0, 0, (32,), 'make_following_mons_nervous'),
    170: (3, 30, 0, 26, (), 'dont_excite_audience'),
    171: (3, 10, 30, 0, (4,), 'badly_startle_prev_mons'),
    172: (1, 40, 0, 0, (9,), 'highly_appealing'),
    173: (2, 40, 0, 0, (10,), 'highly_appealing'),
    174: (4, 30, 0, 40, (), 'next_appeal_later'),
    175: (2, 10, 0, 0, (5,), 'better_when_later'),
    176: (1, 20, 0, 0, (), 'better_if_same_type'),
    177: (0, 30, 0, 0, (), 'affected_by_prev_appeal'),
    178: (1, 20, 10, 0, (), 'startle_mon_with_judges_attention'),
    179: (0, 20, 0, 0, (5,), 'better_if_last'),
    180: (4, 10, 0, 0, (40,), 'better_when_later'),
    181: (1, 40, 0, 17, (23,), 'highly_appealing'),
    182: (2, 10, 0, 0, (36,), 'avoid_startle'),
    183: (0, 30, 0, 0, (), 'next_appeal_earlier'),
    184: (4, 20, 10, 16, (2, 33), 'startle_mon_with_judges_attention'),
    185: (3, 20, 0, 0, (56, 33, 60), 'better_if_first'),
    186: (2, 20, 0, 0, (35,), 'make_following_mons_nervous'),
    187: (2, 10, 0, 25, (), 'improve_condition_prevent_nervousness'),
    188: (4, 20, 10, 43, (42,), 'startle_mon_with_judges_attention'),
    189: (2, 20, 10, 55, (54, 49, 24), 'startle_mon_with_judges_attention'),
    190: (4, 20, 10, 0, (1, 18), 'startle_mon_with_judges_attention'),
    191: (3, 20, 0, 0, (), 'make_following_mons_nervous'),
    192: (0, 40, 0, 0, (18,), 'highly_appealing'),
    193: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    194: (3, 80, 0, 0, (20, 40, 5), 'great_appeal_but_no_more_moves'),
    195: (1, 20, 10, 0, (20, 37), 'badly_startle_mons_with_good_appeals'),
    196: (1, 10, 30, 0, (), 'badly_startle_prev_mons'),
    197: (0, 20, 0, 0, (34,), 'avoid_startle_once'),
    198: (4, 40, 0, 53, (3, 51, 52), 'highly_appealing'),
    199: (3, 30, 0, 18, (), 'dont_excite_audience'),
    200: (0, 40, 40, 0, (), 'jams_others_but_miss_one_turn'),
    201: (4, 30, 0, 24, (), 'scramble_next_turn_order'),
    202: (3, 20, 10, 0, (22,), 'startle_mon_with_judges_attention'),
    203: (4, 20, 0, 5, (), 'avoid_startle_once'),
    204: (2, 20, 10, 35, (), 'startle_mons_same_type_appeal'),
    205: (4, 30, 0, 0, (12, 36), 'dont_excite_audience'),
    206: (0, 10, 30, 0, (7,), 'badly_startle_prev_mons'),
    207: (2, 20, 0, 0, (), 'better_if_first'),
    208: (2, 20, 0, 0, (), 'better_if_same_type'),
    209: (0, 10, 40, 0, (13,), 'badly_startle_front_mon'),
    210: (0, 30, 0, 0, (7,), 'repetition_not_boring'),
    211: (0, 20, 0, 0, (), 'better_if_same_type'),
    212: (1, 20, 0, 20, (40,), 'make_following_mons_nervous'),
    213: (2, 20, 0, 0, (), 'make_following_mons_nervous'),
    214: (2, 30, 0, 0, (10,), 'repetition_not_boring'),
    215: (1, 20, 0, 0, (), 'better_if_last'),
    216: (2, 10, 0, 0, (), 'excite_audience_in_any_contest'),
    217: (2, 30, 0, 0, (), 'repetition_not_boring'),
    218: (2, 10, 0, 0, (), 'excite_audience_in_any_contest'),
    219: (1, 10, 0, 0, (), 'avoid_startle'),
    220: (3, 10, 40, 0, (5,), 'badly_startle_front_mon'),
    221: (1, 40, 0, 0, (9,), 'highly_appealing'),
    222: (4, 10, 0, 0, (), 'better_when_audience_excited'),
    223: (0, 20, 10, 0, (3, 26), 'startle_mon_with_judges_attention'),
    224: (0, 20, 0, 0, (), 'better_if_same_type'),
    225: (0, 10, 30, 27, (28, 29), 'badly_startle_prev_mons'),
    226: (2, 20, 0, 0, (), 'make_following_mons_nervous'),
    227: (2, 20, 0, 0, (), 'make_following_mons_nervous'),
    228: (3, 20, 10, 0, (), 'badly_startle_mons_with_good_appeals'),
    229: (0, 20, 0, 0, (), 'avoid_startle_once'),
    230: (2, 10, 30, 41, (), 'badly_startle_prev_mons'),
    231: (0, 10, 40, 0, (), 'badly_startle_front_mon'),
    232: (0, 40, 0, 0, (48,), 'highly_appealing'),
    233: (0, 30, 0, 0, (56,), 'next_appeal_later'),
    234: (1, 10, 0, 0, (9,), 'quality_depends_on_timing'),
    235: (3, 10, 0, 0, (9,), 'quality_depends_on_timing'),
    236: (1, 10, 0, 0, (9,), 'quality_depends_on_timing'),
    237: (3, 30, 0, 0, (), 'repetition_not_boring'),
    238: (0, 30, 0, 0, (3,), 'affected_by_prev_appeal'),
    239: (0, 30, 0, 0, (), 'scramble_next_turn_order'),
    240: (4, 10, 0, 1, (), 'better_when_audience_excited'),
    241: (1, 10, 0, 9, (), 'better_when_audience_excited'),
    242: (4, 10, 40, 0, (16,), 'badly_startle_front_mon'),
    243: (1, 20, 0, 0, (34,), 'avoid_startle_once'),
    244: (3, 20, 0, 0, (), 'better_if_same_type'),
    245: (0, 30, 0, 0, (), 'next_appeal_earlier'),
    246: (4, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    247: (3, 30, 0, 0, (), 'shift_judge_attention'),
    248: (3, 30, 0, 0, (57, 58, 59, 62), 'dont_excite_audience'),
    249: (4, 10, 0, 0, (), 'better_with_good_condition'),
    250: (1, 30, 0, 0, (1,), 'dont_excite_audience'),
    251: (3, 20, 10, 0, (), 'badly_startle_mons_with_good_appeals'),
    252: (2, 20, 10, 56, (), 'startle_mons_same_type_appeal'),
    253: (2, 30, 0, 0, (), 'scramble_next_turn_order'),
    254: (4, 20, 0, 8, (), 'avoid_startle_once'),
    255: (4, 40, 0, 0, (8,), 'highly_appealing'),
    256: (4, 10, 0, 0, (8,), 'improve_condition_prevent_nervousness'),
    257: (1, 40, 0, 0, (9,), 'highly_appealing'),
    258: (1, 10, 30, 23, (), 'badly_startle_prev_mons'),
    259: (4, 20, 0, 0, (), 'make_following_mons_nervous'),
    260: (3, 20, 0, 0, (35,), 'make_following_mons_nervous'),
    261: (1, 10, 40, 0, (9,), 'badly_startle_front_mon'),
    262: (4, 80, 0, 0, (), 'great_appeal_but_no_more_moves'),
    263: (2, 20, 0, 0, (), 'better_if_last'),
    264: (4, 30, 0, 0, (3,), 'next_appeal_later'),
    265: (3, 20, 30, 0, (), 'startle_prev_mon'),
    266: (2, 30, 0, 0, (), 'dont_excite_audience'),
    267: (1, 10, 0, 0, (), 'better_when_audience_excited'),
    268: (3, 20, 0, 13, (), 'better_if_same_type'),
    269: (3, 20, 0, 34, (), 'make_following_mons_nervous'),
    270: (3, 20, 0, 0, (), 'make_following_mons_nervous'),
    271: (3, 20, 0, 0, (), 'better_if_same_type'),
    272: (2, 10, 0, 0, (), 'appeal_as_good_as_prev_ones'),
    273: (2, 30, 0, 0, (), 'dont_excite_audience'),
    274: (2, 10, 0, 0, (), 'quality_depends_on_timing'),
    275: (3, 10, 0, 0, (), 'avoid_startle'),
    276: (4, 60, 0, 0, (18,), 'user_more_easily_startled'),
    277: (1, 10, 0, 0, (), 'avoid_startle'),
    278: (3, 30, 0, 0, (), 'repetition_not_boring'),
    279: (4, 30, 0, 0, (), 'next_appeal_later'),
    280: (0, 10, 40, 0, (3,), 'badly_startle_front_mon'),
    281: (2, 20, 0, 15, (), 'make_following_mons_nervous'),
    282: (3, 10, 40, 0, (56,), 'badly_startle_front_mon'),
    283: (4, 20, 0, 0, (5,), 'better_if_last'),
    284: (1, 10, 0, 0, (5, 38, 9), 'better_when_later'),
    285: (3, 10, 0, 0, (), 'appeal_as_good_as_prev_ones'),
    286: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    287: (2, 10, 0, 0, (50, 37), 'improve_condition_prevent_nervousness'),
    288: (4, 10, 0, 0, (40,), 'better_when_later'),
    289: (3, 20, 10, 0, (), 'badly_startle_mons_with_good_appeals'),
    290: (3, 10, 0, 0, (), 'better_with_good_condition'),
    291: (1, 20, 0, 31, (1, 30), 'avoid_startle_once'),
    292: (4, 20, 10, 0, (3, 56), 'startle_mon_with_judges_attention'),
    293: (3, 30, 0, 0, (), 'affected_by_prev_appeal'),
    294: (1, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    295: (3, 20, 30, 0, (62,), 'startle_prev_mon'),
    296: (3, 10, 40, 0, (62,), 'badly_startle_front_mon'),
    297: (1, 20, 0, 0, (), 'better_if_last'),
    298: (2, 40, 40, 0, (), 'jams_others_but_miss_one_turn'),
    299: (1, 40, 0, 0, (9,), 'highly_appealing'),
    300: (2, 40, 0, 49, (55, 50), 'highly_appealing'),
    301: (1, 30, 0, 0, (), 'dont_excite_audience'),
    302: (3, 10, 40, 0, (), 'badly_startle_front_mon'),
    303: (2, 10, 0, 0, (15,), 'better_when_later'),
    304: (0, 10, 30, 0, (), 'badly_startle_prev_mons'),
    305: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    306: (0, 10, 40, 0, (7,), 'badly_startle_front_mon'),
    307: (1, 40, 40, 0, (9,), 'jams_others_but_miss_one_turn'),
    308: (1, 40, 40, 0, (1,), 'jams_others_but_miss_one_turn'),
    309: (0, 20, 0, 0, (), 'better_if_same_type'),
    310: (3, 20, 30, 0, (), 'startle_prev_mon'),
    311: (3, 40, 0, 0, (1, 9, 23, 24), 'highly_appealing'),
    312: (3, 20, 0, 0, (), 'better_if_last'),
    313: (3, 20, 0, 0, (), 'better_if_last'),
    314: (0, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    315: (1, 60, 0, 0, (9,), 'user_more_easily_startled'),
    316: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    317: (3, 30, 0, 0, (14,), 'dont_excite_audience'),
    318: (1, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    319: (3, 10, 30, 48, (), 'badly_startle_prev_mons'),
    320: (3, 10, 30, 0, (), 'badly_startle_prev_mons'),
    321: (2, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    322: (0, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    323: (1, 10, 0, 0, (1,), 'better_when_later'),
    324: (1, 30, 0, 0, (), 'scramble_next_turn_order'),
    325: (3, 20, 0, 0, (), 'better_if_first'),
    326: (0, 10, 40, 0, (), 'badly_startle_front_mon'),
    327: (0, 20, 10, 0, (3,), 'startle_mons_same_type_appeal'),
    328: (3, 30, 0, 0, (24,), 'dont_excite_audience'),
    329: (1, 20, 10, 0, (), 'badly_startle_mons_with_good_appeals'),
    330: (4, 20, 10, 0, (1,), 'startle_mon_with_judges_attention'),
    331: (0, 20, 10, 0, (22,), 'badly_startle_mons_with_good_appeals'),
    332: (0, 20, 0, 0, (), 'better_if_first'),
    333: (1, 20, 10, 0, (), 'startle_mons_same_type_appeal'),
    334: (4, 10, 0, 0, (), 'avoid_startle'),
    335: (2, 20, 0, 0, (), 'make_following_mons_nervous'),
    336: (0, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    337: (0, 20, 10, 0, (27, 28, 29), 'startle_mons_same_type_appeal'),
    338: (0, 40, 40, 0, (22,), 'jams_others_but_miss_one_turn'),
    339: (1, 10, 0, 0, (), 'improve_condition_prevent_nervousness'),
    340: (2, 10, 0, 0, (), 'avoid_startle'),
    341: (4, 10, 30, 0, (), 'badly_startle_prev_mons'),
    342: (3, 30, 0, 0, (), 'worsen_condition_of_prev_mons'),
    343: (2, 10, 0, 0, (), 'appeal_as_good_as_prev_ones'),
    344: (0, 60, 0, 0, (13,), 'user_more_easily_startled'),
    345: (1, 20, 0, 0, (22,), 'better_if_first'),
    346: (2, 40, 0, 50, (1, 49), 'highly_appealing'),
    347: (3, 20, 0, 62, (), 'avoid_startle_once'),
    348: (0, 30, 0, 0, (), 'affected_by_prev_appeal'),
    349: (0, 10, 0, 29, (28, 27), 'improve_condition_prevent_nervousness'),
    350: (4, 20, 0, 0, (), 'better_if_same_type'),
    351: (0, 20, 0, 0, (13,), 'better_if_first'),
    352: (1, 30, 0, 0, (1,), 'scramble_next_turn_order'),
    353: (0, 30, 0, 0, (), 'dont_excite_audience'),
    354: (3, 60, 0, 0, (62,), 'user_more_easily_startled'),
}

# sContestExcitementTable: how a move's category stirs the crowd in each contest's category
EXCITEMENT = (
    (+1, 0, -1, -1, 0),     # cool contest
    (0, +1, 0, -1, -1),     # beauty
    (-1, 0, +1, 0, -1),     # cute
    (-1, -1, 0, +1, 0),     # smart
    (0, -1, -1, 0, +1),     # tough
)


def is_combo(prev, move):
    """AreMovesContestCombo: the previous move starts a combo this move finishes."""
    p, m = CONTEST_MOVES.get(prev), CONTEST_MOVES.get(move)
    return bool(p and m and p[3] and p[3] in m[4])


def _score(seq, moves, category, prev=None, rep=0, first_bonus=None, jam_share=0.5):
    """A sequence's score by the plan's rules (plan_moves). first_bonus: the crowd's bonus for the
    first move instead of 10 x excitement, once the applause meter is known (choose_live);
    jam_share: the share of the first move's jam that lands (none when it appeals first)."""
    score = 0
    for n, k in enumerate(seq):
        m = moves[k]
        cat, appeal, jam, _, _, _ = CONTEST_MOVES[m]
        exc = EXCITEMENT[category][cat]
        crowd = first_bonus(exc) if n == 0 and first_bonus else 10 * exc
        s = appeal + jam * (jam_share if n == 0 else 0.5) + crowd
        if prev is not None and is_combo(moves[prev], m):
            s += appeal
        if prev == k:
            rep += 1
            s -= (rep + 1) * 10
        else:
            rep = 0
        score += s
        prev = k
    return score


def plan_moves(moves, category, rounds=5):
    """The DUO's moves for the five rounds, from what it knows before the contest: each move's
    appeal, a combo after its starter (its appeal again), a share of its jam, the crowd's
    excitement (+/-10 for a move in or against the contest's category), and the judges' mark-down
    for the same move twice running ((repeats + 1) x 10). What the others do can't be known
    beforehand. Returns (slots, score, notes) with slots indexing `moves`."""
    import itertools
    slots = [k for k, m in enumerate(moves) if m in CONTEST_MOVES]
    if not slots:
        return [0] * rounds, 0, ["no move this table knows: in slot order"]
    best = None
    for seq in itertools.product(slots, repeat=rounds):
        score = _score(seq, moves, category)
        key = (score, len(set(seq)), [-x for x in seq])
        if best is None or key > best[0]:
            best = (key, list(seq))
    seq = best[1]
    notes = [f"{moves[a]} then {moves[b]}: a combo" for a, b in zip(seq, seq[1:]) if is_combo(moves[a], moves[b])]
    return seq, best[0][0], notes


def choose_live(moves, category, rounds_left, prev=None, rep=0, meter=0, before=0):
    """This round's move once the contest so far is known (11 November): the plan's rules for the
    rounds left, with the first move's crowd bonus as the game gives it - a move the crowd likes
    adds 10, or 60 when it fills the applause meter (meter: where the meter will stand at the DUO's
    turn, 0-4; ContestExcitement's excitementAppealBonus) - and its jam counted only when someone
    appeals before the DUO (before: how many). Returns (slot, score, why)."""
    import itertools
    slots = [k for k, m in enumerate(moves) if m in CONTEST_MOVES]
    if not slots:
        return 0, 0, "no move this table knows"
    fills = lambda exc: (60 if meter + exc > 4 else 10) if exc > 0 else 10 * exc
    best = None
    for seq in itertools.product(slots, repeat=max(1, rounds_left)):
        score = _score(seq, moves, category, prev, rep, fills, 0.5 if before else 0)
        key = (score, len(set(seq)), [-x for x in seq])
        if best is None or key > best[0]:
            best = (key, seq)
    k = best[1][0]
    cat = CONTEST_MOVES[moves[k]][0]
    why = ("it fills the applause meter (+60)" if EXCITEMENT[category][cat] > 0 and meter + 1 > 4 else
           f"a combo after {moves[prev]}" if prev is not None and is_combo(moves[prev], moves[k]) else "the best for the rounds left")
    return k, best[0][0], why


E_MOVE = 7                                   # contest.c's log: the DUO's move, as sent
APPEALS_STATE = (112, 18, 3, 4)              # Task_LinkContest_CommunicateAppealsState's four blocks
STATUS_SIZE = 28                             # struct ContestantStatus


class ContestWatch:
    """The contest so far, from the DUO's record (11 November), and the DUO's move for the next round.
    Each round: the moves, the appeals' state after each of the four appeals, at the round's end
    and before the next (contest.c Task_DoAppeals, Task_EndAppeals, Task_UpdateContestantBoxOrder):
    six groups of four blocks, the leader's copy. From the appeals it follows the applause meter as
    every GBA does (APPEALSTATE_UPDATE_CROWD: the move's excitement, nothing while another's move has
    frozen the crowd, 1 for a move that overrides it, 0 for a liked move repeated; at 5 it empties);
    from the last group it reads the next round's turn order (gContestantTurnOrder) and what the
    others used, and guesses where the meter will be at the DUO's turn if they use their moves'
    categories again."""

    def __init__(self, moves, category, me, rounds=5):
        self.moves, self.category, self.me, self.rounds = list(moves), category, me, rounds
        self.n, self.round, self.groups, self.meter = 0, -1, 0, 0
        self.blocks, self.last = [], None          # (the group being read; the last whole one)
        self.prev, self.rep, self.decided = None, 0, set()
        self.notes = []

    def feed(self, entries):
        for kind, seq, b in entries[self.n:]:
            self.n += 1
            if kind == 2:
                if b[0] | b[1] << 8 == E_MOVE:
                    move = b[2] | b[3] << 8
                    slot = self.moves.index(move) if move in self.moves else None
                    self.rep = self.rep + 1 if slot is not None and slot == self.prev else 0
                    self.prev, self.round, self.groups, self.blocks = slot, self.round + 1, 0, []
                continue
            if kind != 0 or self.round < 0:
                continue
            want = APPEALS_STATE[len(self.blocks)]
            if len(b) != want:
                self.blocks = [b] if len(b) == APPEALS_STATE[0] else []
                continue
            self.blocks.append(b)
            if len(self.blocks) == 4:
                self.groups += 1
                self.last = self.blocks
                if self.groups <= 4:
                    self._appeal(self.blocks)
                self.blocks = []

    def _status(self, status, c):
        return status[STATUS_SIZE * c:STATUS_SIZE * c + STATUS_SIZE]

    def _appeal(self, group):
        status, results, exc, _ = group
        k = self.groups - 1
        c = next((i for i in range(4) if results[i] == k), None)
        if c is None:
            return
        st = self._status(status, c)
        if st[12] & 1 or st[17] >> 2 & 1:          # (nervous, or its turn skipped: no crowd)
            return
        if exc[1] & 1 and c != exc[1] >> 1 & 7:    # (the crowd frozen by another's move)
            return
        r3 = exc[0] - 256 if exc[0] > 127 else exc[0]
        if st[17] >> 4 & 1:                        # overrideCategoryExcitementMod
            r3 = 1
        if r3 > 0 and st[21] & 1:                  # repeatedMove
            r3 = 0
        self.meter = max(0, self.meter + r3)
        if self.meter > 4:
            self.meter = 0

    def ready(self):
        """True once the next round's turn order is known and no choice has been made for it."""
        return (self.groups >= 6 and self.last is not None and 0 <= self.round < self.rounds - 1
                and self.round + 1 not in self.decided)

    def choose(self):
        """(round, slot, why) for the next round."""
        status, _, _, order = self.last
        nxt = self.round + 1
        mine = order[self.me]
        before = sorted((order[c], c) for c in range(4) if c != self.me and order[c] < mine)
        meter = self.meter
        for _, c in before:                        # (the others before us, using their last move's category again)
            st = self._status(status, c)
            move = st[8] | st[9] << 8 or st[6] | st[7] << 8
            if move in CONTEST_MOVES:
                meter = max(0, meter + EXCITEMENT[self.category][CONTEST_MOVES[move][0]])
                if meter > 4:
                    meter = 0
        slot, score, why = choose_live(self.moves, self.category, self.rounds - nxt, self.prev, self.rep,
                                       meter, len(before))
        self.decided.add(nxt)
        note = (f"round {nxt + 1}: appealing {('first', 'second', 'third', 'fourth')[mine & 3]}, the meter at "
                f"{meter} by its turn: {self.moves[slot]} ({why})")
        self.notes.append(note)
        return nxt, slot, note
