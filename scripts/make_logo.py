"""make_logo.py — regenerates the Quest Book logo set (pop-up book with paper heroes).

Edit the shapes/colours here, then run from the repo root:
    python3 scripts/make_logo.py
Writes docs/logo.svg, docs/logo-animated.svg, docs/icon.svg, assets/logo.svg, assets/icon.svg and
build/og.svg. PNG/ICO versions (docs/og.png, docs/favicon.ico, docs/apple-touch-icon.png,
assets/icon.png) are rendered with ImageMagick:
    convert -background none -density 300 docs/icon.svg -resize 256x256 assets/icon.png
    convert -background none -density 300 docs/icon.svg -resize 180x180 docs/apple-touch-icon.png
    convert -background none -density 300 docs/icon.svg -resize 32x32 docs/favicon.ico
    convert -density 96 build/og.svg docs/og.png
"""
import os
# Each figure: list of (svg element without fill, fill colour) — drawn in order. "S:" prefix = stroke-only.
INK = "#2a1e0c"
GOLD, GOLD_D, GOLD_L = "#f0c95a", "#c4952e", "#fbe3a0"
STEEL, STEEL_D = "#e9e2cf", "#b8ab88"
RED, RED_D = "#a83e2c", "#7a2a1d"
BLUE, BLUE_D = "#3f5f8c", "#2c4466"
GREEN, GREEN_D = "#5d7a3e", "#41572a"
SKIN = "#e8c9a0"
LEATHER, LEATHER_D = "#8a5a2b", "#5e3c1b"
PAPER_BACK = "#3a2a12"

KNIGHT = [
 ('<path d="M-13,-92 Q-34,-62 -44,-4 Q-30,-10 -20,-2 Q-12,-34 -4,-66 Z"/>', RED),          # cape
 ('<path d="M-30,-40 Q-38,-22 -44,-4 Q-34,-8 -28,-5 Z"/>', RED_D),
 ('<path d="M-14,-50 L-21,-7 L-29,0 L-8,0 L-4,-28 L4,-28 L8,0 L29,0 L21,-7 L14,-50 Z"/>', STEEL),  # legs
 ('<path d="M2,-28 L4,-28 L8,0 L29,0 L21,-7 L14,-50 L6,-50 Z"/>', STEEL_D),
 ('<path d="M-16,-26 L-8,-26 M10,-26 L18,-26" fill="none" stroke="#8a7a5a" stroke-width="2"/>', None),
 ('<path d="M-29,0 L-8,0 L-8,-6 L-24,-6 Z M8,0 L29,0 L24,-6 L8,-6 Z"/>', LEATHER_D),       # boots
 ('<path d="M-17,-90 Q-21,-70 -15,-48 L15,-48 Q21,-70 17,-90 Q0,-97 -17,-90 Z"/>', GOLD),  # breastplate
 ('<path d="M0,-94 Q9,-94 17,-90 Q21,-70 15,-48 L0,-48 Z"/>', GOLD_D),
 ('<path d="M-6,-86 Q0,-80 6,-86 M0,-82 L0,-56" fill="none" stroke="#8a6418" stroke-width="1.6"/>', None),
 ('<rect x="-16" y="-54" width="32" height="6" rx="2"/>', LEATHER),
 ('<rect x="-3" y="-55" width="6" height="8" rx="1"/>', GOLD_L),
 ('<ellipse cx="-17" cy="-88" rx="9" ry="6"/>', GOLD),
 ('<ellipse cx="17" cy="-88" rx="9" ry="6"/>', GOLD_D),
 ('<path d="M17,-90 L29,-104 L35,-99 L23,-84 Z"/>', STEEL_D),                               # sword arm
 ('<path d="M31,-104 L36,-104 L37,-162 L33.5,-170 L30,-162 Z"/>', STEEL),                   # blade
 ('<path d="M33.5,-170 L37,-162 L36,-104 L33.5,-104 Z"/>', STEEL_D),
 ('<rect x="24" y="-108" width="20" height="5" rx="2"/>', GOLD),
 ('<circle cx="33" cy="-100" r="4.5"/>', LEATHER),
 ('<path d="M-10,-96 L-12,-113 Q0,-127 12,-113 L10,-96 Q0,-99 -10,-96 Z"/>', STEEL),        # helmet
 ('<path d="M1,-125 Q12,-113 10,-96 Q5,-98 1,-98 Z"/>', STEEL_D),
 ('<path d="M-9,-108 L9,-108" fill="none" stroke="#2a1e0c" stroke-width="2.4"/>', None),
 ('<path d="M2,-123 Q12,-146 34,-136 Q22,-134 14,-126 Q22,-128 26,-124 Q14,-122 8,-118 Z"/>', RED),   # plume
 ('<path d="M-42,-88 L-17,-88 L-17,-67 Q-19,-52 -29.5,-44 Q-40,-52 -42,-67 Z"/>', BLUE),   # shield
 ('<path d="M-29.5,-88 L-17,-88 L-17,-67 Q-19,-52 -29.5,-44 Z"/>', BLUE_D),
 ('<path d="M-42,-88 L-17,-88 L-17,-67 Q-19,-52 -29.5,-44 Q-40,-52 -42,-67 Z" fill="none" stroke="#f0c95a" stroke-width="2"/>', None),
 ('<path d="M-29.5,-80 L-26.5,-72 L-29.5,-60 L-32.5,-72 Z"/>', GOLD),
]

WIZARD = [
 ('<path d="M-27,0 Q-21,-40 -12,-74 L12,-74 Q21,-40 29,0 Q15,-7 1,0 Q-13,-7 -27,0 Z"/>', BLUE),   # robe
 ('<path d="M0,-74 L12,-74 Q21,-40 29,0 Q15,-7 1,0 Z"/>', BLUE_D),
 ('<path d="M-6,-40 Q0,-30 -2,0 M8,-50 Q12,-30 14,-4" fill="none" stroke="#24395a" stroke-width="1.6"/>', None),
 ('<path d="M-14,-46 Q0,-42 15,-46 L15,-42 Q0,-38 -14,-42 Z"/>', GOLD),                  # sash
 ('<path d="M-12,-72 Q-31,-58 -34,-38 Q-25,-40 -18,-45 Q-14,-56 -7,-63 Z"/>', BLUE),     # left sleeve
 ('<path d="M10,-72 Q22,-64 28,-60 L28,-50 Q19,-53 8,-58 Z"/>', BLUE_D),                 # right sleeve
 ('<circle cx="30" cy="-55" r="4.5"/>', SKIN),
 ('<path d="M27.5,-148 L32,-148 L32,0 L27.5,0 Z"/>', LEATHER),                           # staff
 ('<path d="M30,-148 L32,-148 L32,0 L30,0 Z"/>', LEATHER_D),
 ('<path d="M26,-146 Q21,-158 29.5,-163 Q38,-158 33,-146" fill="none" stroke="#5e3c1b" stroke-width="2.6"/>', None),
 ('<path d="M29.5,-166 L35,-155 L29.5,-145 L24,-155 Z"/>', GOLD_L),                      # crystal
 ('<path d="M29.5,-166 L35,-155 L29.5,-145 Z"/>', GOLD),
 ('<circle cx="0" cy="-82" r="8.5"/>', SKIN),                                             # face
 ('<path d="M-3.5,-85.5 h2 v2 h-2 Z M1.5,-85.5 h2 v2 h-2 Z"/>', "#2a1e0c"),        # eyes
 ('<path d="M-9,-80 Q-12,-60 0,-44 Q12,-60 9,-80 Q4,-77 0,-79 Q-4,-77 -9,-80 Z"/>', STEEL),   # beard
 ('<path d="M0,-79 Q4,-77 9,-80 Q12,-60 0,-44 Z"/>', STEEL_D),
 ('<ellipse cx="0" cy="-89" rx="24" ry="5"/>', BLUE_D),                                   # hat brim
 ('<path d="M-13,-91 Q-9,-112 3,-130 Q14,-142 25,-135 Q12,-132 9,-115 Q10,-103 13,-91 Q0,-94 -13,-91 Z"/>', BLUE),
 ('<path d="M3,-130 Q14,-142 25,-135 Q12,-132 9,-115 Q10,-103 13,-91 Q6,-93 2,-93 Z"/>', BLUE_D),
 ('<path d="M-1,-112 L1,-107 L6,-106 L2,-103 L3,-98 L-1,-101 L-5,-98 L-4,-103 L-8,-106 L-3,-107 Z"/>', GOLD),
]

ARCHER = [
 ('<path d="M-13,-92 Q-30,-52 -27,-12 Q-19,-18 -12,-14 Q-12,-50 -5,-82 Z"/>', GREEN_D),  # cloak behind
 ('<path d="M8,-106 L17,-110 L24,-70 L15,-66 Z"/>', LEATHER),                            # quiver
 ('<path d="M10,-106 L8,-116 M13,-107 L13,-118 M16,-109 L19,-119" fill="none" stroke="#f0c95a" stroke-width="2.4"/>', None),
 ('<path d="M-10,-42 L-14,0 L-3,0 L0,-26 L3,0 L14,0 L10,-42 Z"/>', LEATHER),             # legs
 ('<path d="M0,-26 L3,0 L14,0 L10,-42 L2,-42 Z"/>', LEATHER_D),
 ('<path d="M-14,0 L-3,0 L-3,-10 L-13,-10 Z M3,0 L14,0 L13,-10 L3,-10 Z"/>', "#3d2a14"),  # boots
 ('<path d="M-14,-90 Q-19,-64 -15,-38 L15,-38 Q19,-64 14,-90 Q0,-95 -14,-90 Z"/>', GREEN),  # tunic
 ('<path d="M0,-93 Q8,-93 14,-90 Q19,-64 15,-38 L0,-38 Z"/>', GREEN_D),
 ('<rect x="-15" y="-50" width="30" height="5" rx="2"/>', LEATHER_D),
 ('<path d="M-12,-86 L-42,-90 L-42,-84 L-12,-79 Z"/>', GREEN_D),                         # bow arm
 ('<path d="M-38,-128 Q-64,-86 -38,-44" fill="none" stroke="#5e3c1b" stroke-width="4.5" stroke-linecap="round"/>', None),
 ('<path d="M-38,-128 L-18,-86 L-38,-44" fill="none" stroke="#efe4c8" stroke-width="1.2"/>', None),
 ('<path d="M-18,-86 L-62,-86" fill="none" stroke="#5e3c1b" stroke-width="2.2"/>', None),
 ('<path d="M-62,-86 L-55,-90 L-55,-82 Z"/>', STEEL),
 ('<circle cx="-42" cy="-87" r="4"/>', SKIN),
 ('<path d="M10,-84 L-14,-88 L-14,-82 L8,-78 Z"/>', GREEN),                              # draw arm
 ('<circle cx="-17" cy="-86" r="4"/>', SKIN),
 ('<path d="M-12,-89 Q-15,-110 0,-119 Q15,-110 12,-89 Q0,-93 -12,-89 Z"/>', GREEN),     # hood
 ('<path d="M0,-119 Q15,-110 12,-89 Q6,-91 0,-91 Z"/>', GREEN_D),
 ('<ellipse cx="0" cy="-99" rx="6.5" ry="7.5"/>', "#1e1408"),
 ('<path d="M-4,-97 Q0,-93 4,-97" fill="none" stroke="#e8c9a0" stroke-width="1.6"/>', None),
]

WHITE, WHITE_D = "#f4f1e8", "#cfc8b4"
BLACK = "#1e1408"
TAN, TAN_D = "#b8925a", "#8f6c3c"
PARROT = "#4e9a3e"

ASTRONAUT = [
 ('<rect x="-25" y="-94" width="12" height="44" rx="3"/>', WHITE_D),                    # backpack
 ('<path d="M-15,-46 L-17,-7 L-23,0 L-4,0 L-3,-28 L3,-28 L4,0 L23,0 L17,-7 L15,-46 Z"/>', WHITE),
 ('<path d="M2,-28 L3,-28 L4,0 L23,0 L17,-7 L15,-46 L6,-46 Z"/>', WHITE_D),
 ('<path d="M-23,0 L-4,0 L-4,-7 L-18,-7 Z M4,0 L23,0 L18,-7 L4,-7 Z"/>', "#6e6a60"),     # boots
 ('<path d="M-16,-24 L-6,-24 M7,-24 L17,-24" fill="none" stroke="#a8822a" stroke-width="2.2"/>', None),
 ('<path d="M-18,-88 Q-31,-70 -29,-52 L-21,-51 Q-22,-67 -12,-80 Z"/>', WHITE_D),        # left arm
 ('<circle cx="-25" cy="-50" r="5"/>', "#6e6a60"),
 ('<path d="M-19,-92 Q-23,-70 -17,-44 L17,-44 Q23,-70 19,-92 Q0,-99 -19,-92 Z"/>', WHITE),  # torso
 ('<path d="M0,-95 Q10,-95 19,-92 Q23,-70 17,-44 L0,-44 Z"/>', WHITE_D),
 ('<rect x="-9" y="-82" width="18" height="13" rx="2"/>', BLUE),                          # chest panel
 ('<circle cx="-4" cy="-75.5" r="2.2"/>', "#d0503a"),
 ('<circle cx="3" cy="-75.5" r="2.2"/>', "#7cc46a"),
 ('<rect x="-17" y="-52" width="34" height="5" rx="2"/>', "#9a9486"),
 ('<path d="M16,-89 L29,-112 L36,-108 L23,-84 Z"/>', WHITE_D),                           # waving arm
 ('<circle cx="33.5" cy="-114" r="5.5"/>', "#6e6a60"),
 ('<circle cx="0" cy="-112" r="18"/>', WHITE),                                            # helmet
 ('<path d="M0,-130 A18,18 0 0 1 0,-94 Z"/>', WHITE_D),
 ('<ellipse cx="2" cy="-110" rx="12.5" ry="10.5"/>', GOLD),                               # visor
 ('<path d="M-6,-115 Q-2,-119 4,-118" fill="none" stroke="#fbe3a0" stroke-width="2.4" stroke-linecap="round"/>', None),
 ('<path d="M11,-126 L16,-138" fill="none" stroke="#6e6a60" stroke-width="2"/>', None),
 ('<circle cx="16.5" cy="-139" r="3"/>', "#d0503a"),
]

PIRATE = [
 ('<path d="M-10,-46 L-12,0 L-2,0 L0,-30 L2,0 L12,0 L10,-46 Z"/>', BLACK),               # boots/legs
 ('<path d="M-18,-90 Q-25,-50 -25,-8 L-11,-14 L-9,-46 L9,-46 L11,-14 L25,-8 Q25,-50 18,-90 Q0,-96 -18,-90 Z"/>', RED),  # coat
 ('<path d="M0,-93 Q10,-93 18,-90 Q25,-50 25,-8 L11,-14 L9,-46 L0,-46 Z"/>', RED_D),
 ('<path d="M-7,-90 L7,-90 L6,-50 L-6,-50 Z"/>', WHITE),                                   # shirt
 ('<path d="M-25,-8 L-11,-14 M25,-8 L11,-14" fill="none" stroke="#f0c95a" stroke-width="2"/>', None),
 ('<rect x="-19" y="-56" width="38" height="6" rx="2"/>', LEATHER_D),
 ('<rect x="-4" y="-57" width="8" height="8" rx="1"/>', GOLD),
 ('<path d="M16,-86 L30,-97 L34,-92 L20,-80 Z"/>', RED_D),                                # sword arm
 ('<path d="M30,-99 Q42,-122 35,-146 Q47,-124 36,-97 Z"/>', STEEL),                        # cutlass
 ('<path d="M26,-97 Q32,-91 39,-97" fill="none" stroke="#f0c95a" stroke-width="2.4"/>', None),
 ('<circle cx="32.5" cy="-95" r="4.2"/>', SKIN),
 ('<circle cx="0" cy="-100" r="9.5"/>', SKIN),                                             # head
 ('<path d="M-9.5,-99 Q-8,-84 0,-82 Q8,-84 9.5,-99 Q0,-93 -9.5,-99 Z"/>', "#3d2a14"),      # beard
 ('<ellipse cx="3.5" cy="-103" rx="3.2" ry="2.6"/>', BLACK),                               # eye patch
 ('<path d="M-9,-107 L7,-101" fill="none" stroke="#1e1408" stroke-width="1.4"/>', None),
 ('<circle cx="-3.5" cy="-103" r="1.2"/>', BLACK),
 ('<path d="M-22,-106 Q-10,-101 0,-103 Q10,-101 22,-106 Q17,-117 8,-119 Q0,-126 -8,-119 Q-17,-117 -22,-106 Z"/>', BLACK),  # tricorn
 ('<path d="M-20,-107 Q-10,-103 0,-105 Q10,-103 20,-107" fill="none" stroke="#f0c95a" stroke-width="1.8"/>', None),
 ('<path d="M-3,-117 L0,-113 L3,-117 M-3,-113 L3,-117" fill="none" stroke="#f4f1e8" stroke-width="1.4"/>', None),
 ('<path d="M-20,-90 L-24,-72 L-17,-80 Z"/>', RED),                                        # parrot tail
 ('<ellipse cx="-17" cy="-96" rx="5.5" ry="8"/>', PARROT),                                 # parrot
 ('<circle cx="-16" cy="-105" r="4.5"/>', PARROT),
 ('<path d="M-12,-106 L-8,-104 L-12,-102 Z"/>', GOLD),
 ('<circle cx="-15" cy="-106" r="1"/>', BLACK),
]

DETECTIVE = [
 ('<path d="M-11,-30 L-12,0 L-3,0 L-2,-30 Z M2,-30 L3,0 L12,0 L11,-30 Z"/>', "#3a3a44"),  # trousers
 ('<path d="M-14,0 L-2,0 L-2,-5 L-13,-5 Z M2,0 L14,0 L13,-5 L2,-5 Z"/>', BLACK),          # shoes
 ('<path d="M-17,-90 Q-24,-50 -26,-10 L-4,-12 L-3,-34 L3,-34 L4,-12 L26,-10 Q24,-50 17,-90 Q0,-96 -17,-90 Z"/>', TAN),  # trench coat
 ('<path d="M0,-93 Q9,-93 17,-90 Q24,-50 26,-10 L4,-12 L3,-34 L0,-34 Z"/>', TAN_D),
 ('<rect x="-19" y="-58" width="38" height="5" rx="2"/>', TAN_D),
 ('<path d="M-8,-90 L0,-72 L8,-90 Z"/>', WHITE),                                           # shirt
 ('<path d="M-2,-86 L2,-86 L1.5,-74 L0,-71 L-1.5,-74 Z"/>', RED_D),                       # tie
 ('<path d="M-12,-91 L0,-72 M12,-91 L0,-72" fill="none" stroke="#6e5230" stroke-width="2"/>', None),
 ('<path d="M-6,-50 L-5,-30 M6,-50 L5,-30" fill="none" stroke="#6e5230" stroke-width="1.4"/>', None),
 ('<path d="M16,-86 L28,-92 L31,-86 L19,-80 Z"/>', TAN_D),                                # arm
 ('<path d="M33,-97 L38,-108" fill="none" stroke="#5e3c1b" stroke-width="4" stroke-linecap="round"/>', None),
 ('<circle cx="29" cy="-89" r="4"/>', SKIN),
 ('<circle cx="40" cy="-114" r="9"/>', "#cfe3ea"),                                         # magnifier lens
 ('<circle cx="40" cy="-114" r="9" fill="none" stroke="#a8822a" stroke-width="2.6"/>', None),
 ('<path d="M35,-118 Q37,-121 41,-121" fill="none" stroke="#ffffff" stroke-width="1.6"/>', None),
 ('<circle cx="0" cy="-100" r="9"/>', SKIN),                                               # head
 ('<path d="M-4,-101 h2 M2,-101 h2" fill="none" stroke="#2a1e0c" stroke-width="1.6"/>', None),
 ('<ellipse cx="0" cy="-106" rx="17" ry="3.8"/>', "#3a3a44"),                              # fedora brim
 ('<path d="M-10,-107 Q-11,-120 0,-122 Q11,-120 10,-107 Z"/>', "#4a4a56"),
 ('<path d="M0,-122 Q11,-120 10,-107 L0,-107 Z"/>', "#3a3a44"),
 ('<rect x="-10.5" y="-111" width="21" height="3.5"/>', BLACK),
]


ROBO, ROBO_D, ROBO_EYE = "#aab4be", "#7f8a96", "#7fd6e6"
NAVY = "#2c3348"
SHIRT = "#c96a3a"
DENIM = "#3f5f8c"
ROPE = "#c9a86a"

ROBOT = [
 ('<rect x="-15" y="-42" width="10" height="38" rx="2"/>', ROBO),
 ('<rect x="5" y="-42" width="10" height="38" rx="2"/>', ROBO_D),
 ('<rect x="-21" y="-6" width="17" height="6" rx="2"/>', "#5d6670"),
 ('<rect x="4" y="-6" width="17" height="6" rx="2"/>', "#5d6670"),
 ('<path d="M-20,-84 L-30,-66 L-27,-50 L-22,-52 L-24,-64 L-16,-76 Z"/>', ROBO_D),            # left arm
 ('<path d="M-29,-52 L-32,-44 M-24,-51 L-23,-43" fill="none" stroke="#5d6670" stroke-width="2.4"/>', None),
 ('<rect x="-21" y="-90" width="42" height="50" rx="5"/>', ROBO),                              # torso
 ('<path d="M0,-90 L16,-90 Q21,-90 21,-85 L21,-45 Q21,-40 16,-40 L0,-40 Z"/>', ROBO_D),
 ('<circle cx="-8" cy="-72" r="6"/>', GOLD),
 ('<path d="M-8,-72 L-5,-76" fill="none" stroke="#2a1e0c" stroke-width="1.6"/>', None),
 ('<rect x="3" y="-78" width="12" height="4" rx="1"/>', "#d0503a"),
 ('<rect x="3" y="-70" width="12" height="4" rx="1"/>', "#7cc46a"),
 ('<path d="M-14,-52 L14,-52" fill="none" stroke="#5d6670" stroke-width="2"/>', None),
 ('<path d="M18,-84 L31,-102 L36,-98 L23,-80 Z"/>', ROBO_D),                                   # waving arm
 ('<path d="M32,-104 L30,-113 M35,-102 L42,-108" fill="none" stroke="#5d6670" stroke-width="2.8" stroke-linecap="round"/>', None),
 ('<rect x="-4" y="-96" width="8" height="7"/>', "#5d6670"),
 ('<rect x="-16" y="-124" width="32" height="28" rx="5"/>', ROBO),                             # head
 ('<path d="M0,-124 L11,-124 Q16,-124 16,-119 L16,-101 Q16,-96 11,-96 L0,-96 Z"/>', ROBO_D),
 ('<circle cx="-6.5" cy="-112" r="4.6"/>', ROBO_EYE),
 ('<circle cx="6.5" cy="-112" r="4.6"/>', ROBO_EYE),
 ('<circle cx="-6.5" cy="-112" r="1.6"/>', "#1e1408"),
 ('<circle cx="6.5" cy="-112" r="1.6"/>', "#1e1408"),
 ('<path d="M-7,-102 L7,-102 M-7,-99.5 L7,-99.5" fill="none" stroke="#5d6670" stroke-width="1.4"/>', None),
 ('<path d="M0,-124 L0,-134" fill="none" stroke="#5d6670" stroke-width="2"/>', None),
 ('<circle cx="0" cy="-136" r="3.4"/>', "#d0503a"),
]

SAMURAI = [
 ('<path d="M-21,0 L-14,-46 L14,-46 L21,0 L4,0 L0,-24 L-4,0 Z"/>', NAVY),                      # hakama
 ('<path d="M0,-24 L4,0 L21,0 L14,-46 L1,-46 Z"/>', "#20263a"),
 ('<path d="M-8,-40 L-11,-4 M8,-40 L11,-4" fill="none" stroke="#454e6a" stroke-width="1.4"/>', None),
 ('<path d="M-17,-88 Q-20,-66 -15,-46 L15,-46 Q20,-66 17,-88 Q0,-94 -17,-88 Z"/>', RED),      # do (armour)
 ('<path d="M0,-91 Q9,-91 17,-88 Q20,-66 15,-46 L0,-46 Z"/>', RED_D),
 ('<path d="M-17,-76 L17,-76 M-17,-66 L17,-66 M-16,-56 L16,-56" fill="none" stroke="#f0c95a" stroke-width="1.4"/>', None),
 ('<rect x="-16" y="-50" width="32" height="5" rx="1"/>', WHITE),                             # obi
 ('<path d="M-31,-89 L-15,-91 L-15,-70 L-29,-68 Z"/>', RED),                                   # sode
 ('<path d="M15,-91 L31,-89 L29,-68 L15,-70 Z"/>', RED_D),
 ('<path d="M-30,-82 L-15,-84 M-29,-75 L-15,-77 M15,-84 L30,-82 M15,-77 L29,-75" fill="none" stroke="#f0c95a" stroke-width="1.2"/>', None),
 ('<path d="M14,-84 L27,-104 L32,-100 L20,-80 Z"/>', RED_D),                                   # sword arm
 ('<path d="M31,-108 L34,-106 L58,-150 L55,-152 Z"/>', STEEL),                                 # katana blade
 ('<path d="M31,-106 L26,-96" fill="none" stroke="#1e1408" stroke-width="3.4" stroke-linecap="round"/>', None),
 ('<circle cx="31.5" cy="-106.5" r="3.6"/>', GOLD),
 ('<circle cx="29" cy="-101" r="4"/>', SKIN),
 ('<path d="M-17,-103 L17,-103 L20,-93 L-20,-93 Z"/>', BLACK),                                # neck guard
 ('<circle cx="0" cy="-100" r="8.5"/>', SKIN),
 ('<path d="M-4,-101 L-1,-100 M1,-100 L4,-101" fill="none" stroke="#2a1e0c" stroke-width="1.6"/>', None),
 ('<path d="M-12,-104 Q-12,-119 0,-120 Q12,-119 12,-104 Z"/>', BLACK),                        # kabuto
 ('<path d="M-1.5,-119 Q-10,-130 -17,-142 Q-5,-133 0,-124 Q5,-133 17,-142 Q10,-130 1.5,-119 Z"/>', GOLD),  # crest
]

COWBOY = [
 ('<path d="M-11,-46 L-13,-6 L-3,-6 L0,-28 L3,-6 L13,-6 L11,-46 Z"/>', DENIM),                # jeans
 ('<path d="M0,-28 L3,-6 L13,-6 L11,-46 L1,-46 Z"/>', BLUE_D),
 ('<path d="M-15,0 L-2,0 L-3,-10 L-13,-10 Z M2,0 L15,0 L13,-10 L3,-10 Z"/>', LEATHER_D),     # boots
 ('<path d="M-15,-84 Q-24,-72 -19,-58 L-14,-60 Q-17,-70 -11,-78 Z"/>', SHIRT),                # hand on hip
 ('<path d="M-15,-88 Q-19,-66 -14,-44 L14,-44 Q19,-66 15,-88 Q0,-93 -15,-88 Z"/>', SHIRT),    # shirt
 ('<path d="M-15,-88 Q-19,-66 -14,-44 L-5,-44 L-6,-85 Z"/>', LEATHER),                        # vest
 ('<path d="M15,-88 Q19,-66 14,-44 L5,-44 L6,-85 Z"/>', LEATHER_D),
 ('<rect x="-15" y="-50" width="30" height="5" rx="2"/>', "#3d2a14"),
 ('<rect x="-5" y="-51.5" width="10" height="8" rx="2"/>', GOLD),
 ('<path d="M-8,-91 L8,-91 L0,-80 Z"/>', RED),                                                 # bandana
 ('<path d="M14,-84 L26,-101 L31,-97 L20,-80 Z"/>', SHIRT),                                    # lasso arm
 ('<ellipse cx="38" cy="-124" rx="17" ry="6" fill="none" stroke="#c9a86a" stroke-width="2.6"/>', None),
 ('<path d="M29,-102 Q30,-112 26,-122" fill="none" stroke="#c9a86a" stroke-width="2.4"/>', None),
 ('<circle cx="28.5" cy="-102" r="4"/>', SKIN),
 ('<circle cx="0" cy="-99" r="8.5"/>', SKIN),
 ('<path d="M-4,-100 h2 M2,-100 h2" fill="none" stroke="#2a1e0c" stroke-width="1.6"/>', None),
 ('<path d="M-10,-106 Q-11,-119 -4,-120 Q0,-117 4,-120 Q11,-119 10,-106 Z"/>', LEATHER),       # hat crown
 ('<path d="M-23,-105 Q-12,-100 0,-101 Q12,-100 23,-105 Q15,-109 0,-108 Q-15,-109 -23,-105 Z"/>', LEATHER_D),  # brim
 ('<rect x="-10" y="-110" width="20" height="3"/>', "#3d2a14"),
]


def _with_fill(el, fill, stroke=None):
    attrs = ""
    if fill:
        attrs += f' fill="{fill}"'
    if stroke:
        attrs += f' stroke="{stroke}" stroke-width="1.1" stroke-linejoin="round"'
    return el.replace("/>", attrs + "/>", 1) if fill else el

def figure(parts, x, y, s=1.0, cls=""):
    """Paper cut-out: a dark 'thickness' copy offset behind, then the coloured figure, then a fold tab."""
    c = f' class="{cls}"' if cls else ""
    back = []
    for el, fill in parts:
        if fill:
            back.append(el.replace("/>", f' fill="{PAPER_BACK}"/>', 1))
        else:
            back.append(el.replace('stroke="', f'stroke="{PAPER_BACK}" data-x="', 1))
    front = [_with_fill(el, fill, INK if fill else None) for el, fill in parts]
    tab = '<path d="M-30,0 L30,0 L36,9 L-24,9 Z" fill="#b9a983" stroke="#8a7a5a" stroke-width="1"/>'
    # the animation class sits on an INNER group: a CSS transform would replace the outer
    # group's translate/scale attribute and send the figure to the corner
    return (f'<g transform="translate({x},{y}) scale({s})"><g{c}>'
            + tab + f'<g transform="translate(3.5,2.5)">{"".join(back)}</g>' + "".join(front) + '</g></g>')


def star(cx, cy, r, fill="#f0c95a"):
    k = r * 0.28
    return (f'<path d="M{cx},{cy-r} L{cx+k},{cy-k} L{cx+r},{cy} L{cx+k},{cy+k} L{cx},{cy+r} '
            f'L{cx-k},{cy+k} L{cx-r},{cy} L{cx-k},{cy-k} Z" fill="{fill}"/>')

BOOK = '''<path d="M52,338 Q160,330 260,362 Q360,330 468,338 L468,350 Q360,344 260,374 Q160,344 52,350 Z" fill="#4a3216" stroke="#d4a843" stroke-width="1.5"/>
<path d="M60,330 Q160,322 260,352 L260,362 Q160,334 60,341 Z" fill="#c9b994"/>
<path d="M460,330 Q360,322 260,352 L260,362 Q360,334 460,341 Z" fill="#b9a983"/>
<path d="M60,330 Q160,322 260,352 L260,262 Q180,240 105,248 Z" fill="#e8dcc0" stroke="#d4a843" stroke-width="2"/>
<path d="M460,330 Q360,322 260,352 L260,262 Q340,240 415,248 Z" fill="#ddd0b0" stroke="#d4a843" stroke-width="2"/>
<path d="M95,300 Q170,292 240,312 M100,282 Q172,274 240,292 M425,300 Q350,292 280,312 M420,282 Q348,274 280,292" fill="none" stroke="#b9a983" stroke-width="1.5"/>'''

SLOTS = [(150, 284, 0.95), (262, 304, 1.0), (374, 284, 0.95)]   # left, centre, right
STATIC_TRIO = (WIZARD, ASTRONAUT, PIRATE)          # one hero from three different worlds
ANIMATED_SETS = [(WIZARD, ASTRONAUT, PIRATE),      # each trio mixes three different worlds
                 (DETECTIVE, KNIGHT, ROBOT),
                 (COWBOY, SAMURAI, ARCHER)]


def scene(animated=False):
    sparkle = star(198, 112, 9) + star(214, 92, 5) + star(168, 100, 4, "#e8dcc0")
    out = BOOK
    if not animated:
        for parts, (x, y, s) in zip(STATIC_TRIO, SLOTS):
            out += figure(parts, x, y, s)
        return out + sparkle
    for si, trio in enumerate(ANIMATED_SETS):
        for k, (parts, (x, y, s)) in enumerate(zip(trio, SLOTS)):
            out += figure(parts, x, y, s, cls=f"pop set{si} d{k}")
    return out + f'<g class="spark">{sparkle}</g>'


ANIM = '''<style>
.pop{transform-box:fill-box;transform-origin:50% 100%;animation:15s ease-in-out infinite both}
.set0{animation-name:set0}.set1{animation-name:set1}.set2{animation-name:set2}
.d1{animation-delay:.18s}.d2{animation-delay:.36s}
.spark{animation:tw 2.4s ease-in-out 1s infinite}
@keyframes set0{0%{transform:scaleY(0)}4%{transform:scaleY(1.08)}6%,28%{transform:scaleY(1)}32%,100%{transform:scaleY(0)}}
@keyframes set1{0%,33.3%{transform:scaleY(0)}37.3%{transform:scaleY(1.08)}39.3%,61.3%{transform:scaleY(1)}65.3%,100%{transform:scaleY(0)}}
@keyframes set2{0%,66.6%{transform:scaleY(0)}70.6%{transform:scaleY(1.08)}72.6%,94.6%{transform:scaleY(1)}98.6%,100%{transform:scaleY(0)}}
@keyframes tw{0%,100%{opacity:1}50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.pop,.spark{animation:none}.set1,.set2{transform:scaleY(0)}}
</style>'''

def logo(animated=False):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="40 70 440 310" role="img" aria-label="Quest Book logo">'
            + (ANIM if animated else "") + scene(animated) + '</svg>\n')

def icon(bg=True):
    k = figure(ASTRONAUT, 577, 214, 0.52)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="515 115 120 120" role="img" aria-label="Quest Book">'
            + ('<rect x="515" y="115" width="120" height="120" rx="24" fill="#14100a"/>' if bg else "")
            + '<path d="M522,214 Q548,206 575,219 L575,188 Q552,178 530,184 Z" fill="#e8dcc0" stroke="#d4a843" stroke-width="2"/>'
            + '<path d="M628,214 Q602,206 575,219 L575,188 Q598,178 620,184 Z" fill="#ddd0b0" stroke="#d4a843" stroke-width="2"/>'
            + k + '</svg>\n')

def og():
    lg = scene()
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">'
            '<rect width="1200" height="630" fill="#0c0a07"/>'
            f'<g transform="translate(10,40) scale(1.3) translate(-40,-60)">{lg}</g>'
            '<text x="880" y="270" text-anchor="middle" font-family="DejaVu Serif, Georgia, serif" font-size="78" fill="#d4a843">QUEST</text>'
            '<text x="880" y="360" text-anchor="middle" font-family="DejaVu Serif, Georgia, serif" font-size="78" fill="#d4a843">BOOK</text>'
            '<text x="880" y="430" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="28" fill="#c8b49a">choose your own adventure</text>'
            '</svg>\n')

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.makedirs(f"{root}/build", exist_ok=True)
os.makedirs(f"{root}/assets", exist_ok=True)
files = {"docs/logo.svg": logo(), "docs/logo-animated.svg": logo(True), "docs/icon.svg": icon(),
         "assets/logo.svg": logo(), "assets/icon.svg": icon(), "build/og.svg": og()}
for p, c in files.items():
    open(p if p.startswith("/") else f"{root}/{p}", "w").write(c)
print("ok")
