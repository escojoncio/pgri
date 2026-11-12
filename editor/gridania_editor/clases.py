"""Clase de texto de una hoja (UNICO sitio donde se define el mapeo). clase_de(hoja) -> nombre de clase; 'Otros' por defecto."""
import functools

OTROS = 'Otros'
# (nombre, hojas exactas, prefijos de ruta). Se evalua en este orden.
_REGLAS = [
    ('Escenas', (), ('cut_scene/', 'CutScene', 'Cutscene')),
    ('Misiones', ('Quest', 'Journal', 'JournalCategory', 'JournalGenre', 'JournalSection', 'LegacyQuest', 'CompleteJournal', 'QuestRewardOther', 'QuestBattle'), ('quest/', 'Quest', 'Journal')),
    ('Dialogo de PNJ', ('ENpcResident', 'DefaultTalk', 'Balloon', 'NpcYell', 'CustomTalk', 'GimmickTalk', 'SnipeTalk', 'GoldSaucerTalk', 'ContentTalk', 'CraftLeveTalk', 'GuildleveAssignmentTalk', 'HalloweenNpcSelect'), ('custom/', 'CustomTalk')),
    ('Objetos', ('Item', 'EventItem', 'EventItemHelp', 'EventItemCategory', 'ItemUICategory', 'ItemSearchCategory', 'ItemSeries', 'ItemSpecialBonus', 'Mount', 'MountTransient', 'Companion', 'CompanionTransient', 'Ornament', 'OrnamentTransient', 'Glasses', 'Stain', 'Title'), ('Item', 'EventItem')),
    ('Habilidades y acciones', ('Action', 'ActionTransient', 'ActionCategory', 'Status', 'Trait', 'TraitTransient', 'CraftAction', 'GeneralAction', 'PetAction', 'BuddyAction', 'EventAction', 'CompanyAction', 'MainCommand', 'ExtraCommand', 'Emote', 'EmoteCategory', 'ClassJob', 'ClassJobCategory'), ('Action', 'Status', 'Trait', 'ClassJob')),
    ('Lugares', ('PlaceName', 'TerritoryType', 'Map', 'Aetheryte', 'FishingSpot', 'GatheringPointName', 'ContentFinderCondition', 'ContentFinderConditionTransient', 'InstanceContentTextData', 'PublicContent', 'PublicContentTextData', 'Fate', 'DynamicEvent'), ('PlaceName', 'Territory', 'Housing')),
    ('Interfaz', ('Addon', 'AddonTransient', 'AddonParam', 'EmjAddon', 'FGSAddon', 'Lobby', 'LogMessage', 'LogFilter', 'LogKind', 'Error', 'Hud', 'ConfigKey', 'TextCommand', 'TextCommandParam', 'HowTo', 'HowToPage', 'HowToCategory', 'ContentsTutorial', 'ContentsTutorialPage', 'EventTutorial', 'EventTutorialPage', 'MultipleHelp', 'MultipleHelpString', 'GuidePageString', 'GuideTitle', 'Description', 'DescriptionString', 'OnlineStatus', 'QuickChat', 'QuickChatTransient', 'Opening', 'Attributive', 'CharaMakeName'), ('Addon', 'Lobby', 'LogMessage', 'Hud', 'Chara', 'HowTo')),
    ('Logros, levis y otros', ('Achievement', 'AchievementCategory', 'AchievementKind', 'Leve', 'LeveString', 'LeveClient', 'LeveAssignmentType', 'Orchestrion', 'OrchestrionCategory', 'OrchestrionPath', 'BNpcName', 'EObjName', 'MonsterNote', 'Completion', 'KTGTypeWordTextData'), ('Achievement', 'Leve', 'Orchestrion', 'WKS')),
]
CLASES = ['Dialogo de PNJ', 'Misiones', 'Escenas', 'Objetos', 'Habilidades y acciones', 'Lugares', 'Interfaz', 'Logros, levis y otros', OTROS]


@functools.lru_cache(maxsize=None)
def clase_de(hoja):
    """hoja (ej. 'quest/000/ManFst002_00085', 'ENpcResident', 'cut_scene/022/x') -> clase"""
    hoja = hoja or ''
    for nombre, exactas, prefijos in _REGLAS:
        if hoja in exactas: return nombre
    for nombre, exactas, prefijos in _REGLAS:
        if any(hoja.startswith(p) for p in prefijos): return nombre
    return OTROS
