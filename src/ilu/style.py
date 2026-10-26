"""Colour palettes. Every colour is '#RRGGBB' in sRGB."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    name: str
    house: tuple[str, ...]  # painted walls of ordinary buildings
    plinth: tuple[str, ...]  # the darker band along the base of a wall
    concrete: tuple[str, ...]  # walls of large institutional blocks
    slab: tuple[str, ...]  # flat concrete roofs
    sheet: tuple[str, ...]  # pitched metal or tile roofs
    tanks: tuple[str, ...]  # rooftop water tanks
    tank_chance: float  # share of flat roofs with a tank
    road: str
    walk: str
    kerb: str
    ground: dict[str, str]  # area kind -> colour
    trunk: str
    leaves: tuple[str, ...]
    cover: dict[int, str]  # ESA WorldCover class -> ground colour


WEST_AFRICA = Style(
    name='west-africa',
    house=('#F2E8D5', '#E8D7A8', '#D7E3CC', '#E6CDB5', '#CFDDE8', '#EFE9DE', '#E9D2C0', '#EEE4CF'),
    plinth=('#7A3B32', '#8A6A4E', '#7E7A74', '#9C5A3C', '#5F6B5A'),
    concrete=('#A39886', '#968B7A', '#ADA290', '#9C9180'),
    slab=('#CBC3B6', '#BDB4A6', '#D3CDC2'),
    sheet=('#8E5A3E', '#B9BEC0', '#7F8C95', '#9E2F2A', '#2F5C8F', '#3E6B4A', '#6B4A33'),
    tanks=('#1F1F22', '#1F1F22', '#2E5FA8', '#E8E6E0'),
    tank_chance=0.45,
    road='#3B3B3D',
    walk='#B9765A',
    kerb='#D9D4CA',
    ground={
        'water': '#3F86AE',
        'wood': '#5E7F4A',
        'grass': '#8DB06A',
        'cemetery': '#7E9A63',
        'parking': '#5A5A5C',
        'pitch': '#7FAE5A',
        'track': '#A8483A',
        'pool': '#3FA9D6',
    },
    trunk='#5A4433',
    leaves=('#4F7A3A', '#5E8A3F', '#3F6B35'),
    cover={
        10: '#4E7339',  # trees: shaded forest floor
        20: '#7C8A4E',  # shrubland
        30: '#8DB06A',  # grassland
        40: '#A7AE63',  # cropland
        50: '#A79B84',  # built-up: the yards, verges and lawns between buildings
        60: '#C08A62',  # bare: red laterite
        70: '#F2F4F5',  # snow
        80: '#3F86AE',  # water
        90: '#6E9467',  # herbaceous wetland
        95: '#3E6448',  # mangroves
        100: '#9AA67A',  # moss and lichen
    },
)

PLAIN = Style(
    name='plain',
    house=('#E6E3DE', '#DCD8D2', '#EDEAE5', '#D3CFC9'),
    plinth=('#8C8883', '#7F7B76'),
    concrete=('#B5B1AB', '#A9A59F', '#BDB9B3'),
    slab=('#C9C6C1', '#BDBAB5'),
    sheet=('#7D7A76', '#8E8A85', '#6F6C68'),
    tanks=('#9A9690',),
    tank_chance=0.0,
    road='#4A4A4C',
    walk='#BDBAB4',
    kerb='#D6D3CE',
    ground={
        'water': '#6E9DB8',
        'wood': '#6F8A63',
        'grass': '#A3BA8C',
        'cemetery': '#97A887',
        'parking': '#6A6A6C',
        'pitch': '#93B07F',
        'track': '#A65A4E',
        'pool': '#6DB6D6',
    },
    trunk='#5E5248',
    leaves=('#6B8A5C', '#5F7D52'),
    cover={
        10: '#5F7A55',
        20: '#8A9068',
        30: '#A3BA8C',
        40: '#B5B888',
        50: '#B8B2A8',
        60: '#C9B99C',
        70: '#F2F4F5',
        80: '#6E9DB8',
        90: '#87A07E',
        95: '#55705C',
        100: '#A8AE90',
    },
)

STYLES = {s.name: s for s in (WEST_AFRICA, PLAIN)}

# How OSM `surface` values look. These describe real materials, so every
# style shares them; a pitch without a surface tag uses the style's colour.
SURFACE = {
    'grass': '#7FAE5A',
    'artificial_turf': '#4FA34A',
    'clay': '#B5653A',
    'sand': '#D8C38E',
    'ground': '#A88B64',
    'dirt': '#A88B64',
    'earth': '#A88B64',
    'gravel': '#A9A49A',
    'fine_gravel': '#B3AC9F',
    'compacted': '#B2A58C',
    'unpaved': '#B39A73',
    'asphalt': '#4A4A4C',
    'paved': '#8E8B85',
    'concrete': '#B9B6AF',
    'paving_stones': '#A8A29A',
    'sett': '#8F8A82',
    'tartan': '#A8483A',
    'acrylic': '#3F7F5F',
    'wood': '#9C7A52',
}

LINE = '#F4F4F0'  # sport markings
