"""Lightweight UI translation helpers for the desktop app."""

from __future__ import annotations

import re

from PyQt6 import QtCore, QtWidgets

from poker.tools.helper import get_config

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "fr")

TRANSLATIONS = {
    "fr": {
        "All": "Tous",
        "Settings": "Parametres",
        "Setup": "Parametres",
        "Table Setup": "Configuration de table",
        "Documentation": "Documentation",
        "Supported Rooms": "Rooms compatibles",
        "Open GitHub Guide": "Ouvrir le guide GitHub",
        "Act automatically": "Agir automatiquement",
        "Start": "Demarrer",
        "Stop": "Arreter",
        "Strategy Analyser": "Analyseur de strategie",
        "Strategy Editor": "Editeur de strategie",
        "Genetic Algorithm": "Algorithme genetique",
        "Discord Chat": "Chat Discord",
        "Bot absolute equity": "Equite absolue du bot",
        "Bot range equity": "Equite de range du bot",
        "Bot relative equity": "Equite relative du bot",
        "Bot preflop sheet": "Table preflop du bot",
        "Opponent range": "Range adverse",
        "Bot cards": "Cartes du bot",
        "Table cards": "Cartes du tableau",
        "Collusion cards": "Cartes de collusion",
        "Montecarlo runs": "Iterations Monte Carlo",
        "Other player has initiative": "L'adversaire a l'initiative",
        "Hand number": "Numero de main",
        "Last Decision": "Derniere decision",
        "I'm ready!": "Je suis pret !",
        "Learn to recognize a different table": "Apprendre a reconnaitre une autre table",
        "Choose the strategy that the bot should use to play": "Choisissez la strategie que le bot doit utiliser",
        "Last made decision by the bot": "Derniere decision prise par le bot",
        "Change the table interpratation. Restart required to take effect.": "Changer l'interpretation de la table. Redemarrage requis.",
        "BB wins per 100 hands": "BB gagnees pour 100 mains",
        "Assumed players": "Joueurs supposes",
        "Minimum call equity after adj": "Equite min. de call apres ajust.",
        "Minimum bet equity after adj": "Equite min. de mise apres ajust.",
        "Required call (or pot multiple)": "Call requis (ou multiple du pot)",
        "Required bet (or pot multiple)": "Mise requise (ou multiple du pot)",
        "Direct Mouse control and Virtual Machines": "Controle direct de la souris et machines virtuelles",
        "Timeout": "Delai d'attente",
        "Login": "Identifiant",
        "Password": "Mot de passe",
        "Save": "Enregistrer",
        "Language": "Langue",
        "Strategy editor": "Editeur de strategie",
        "Select Strategy": "Choisir une strategie",
        "New name": "Nouveau nom",
        "Save under new name": "Enregistrer sous un nouveau nom",
        "Table Parameters": "Parametres de table",
        "Logging": "Journalisation",
        "Gather player names": "Recuperer les noms des joueurs",
        "Participate in collusion": "Participer a la collusion",
        "Blinds": "Blinds",
        "Small Blind (cents)": "Petite blind (centimes)",
        "Big Blind (cents)": "Grosse blind (centimes)",
        "PreFlop": "Preflop",
        "Betting": "Mises",
        "Curvature": "Courbure",
        "Table setup": "Configuration de table",
        "Search areas": "Zones de recherche",
        "Button Images and their search areas": "Images des boutons et leurs zones de recherche",
        "Raise Button": "Bouton de relance",
        "Show": "Afficher",
        "All in call Button": "Bouton de call all-in",
        "\"My turn\" search area": "Zone de recherche \"mon tour\"",
        "Fast Fold Button": "Bouton de fold rapide",
        "Fold Button": "Bouton de fold",
        "Check Button": "Bouton de check",
        "Resume Hand": "Reprendre la main",
        "\"My Turn\" image": "Image \"Mon tour\"",
        "I'm back": "Je suis de retour",
        "Call Button": "Bouton de call",
        "Lost everything search area": "Zone de recherche \"tout perdu\"",
        "Lost everything image": "Image \"tout perdu\"",
        "Buttons search area": "Zone de recherche des boutons",
        "Strategy Analyser": "Analyseur de strategie",
        "Action at End Stage": "Action en fin de coup",
        "Strategy": "Strategie",
        "End Stage": "Etape finale",
        "Choose what kind of decision you want to analyse in more detail.": "Choisissez le type de decision a analyser plus en detail.",
        "Choose the strategy you would like to analyse. '.*' means all strategies together.": "Choisissez la strategie a analyser. '.*' signifie toutes les strategies regroupees.",
        "Choose the game stage you want to focus on.": "Choisissez l'etape du coup sur laquelle vous voulez vous concentrer.",
        "Return in bb per 100 hands": "Rendement en bb pour 100 mains",
        "Total played hands": "Nombre total de mains jouees",
        "Shows best strategies that have played at least 500 hands": "Affiche les meilleures strategies ayant joue au moins 500 mains",
        "Show League Table": "Afficher le classement",
        "Equity Histogram": "Histogramme d'equite",
        "Show rounds within stages": "Afficher les tours dans les etapes",
        "Played on my computer only": "Jouees sur mon ordinateur uniquement",
        "Scatter Plot": "Nuage de points",
        "Worst Hands": "Pires mains",
        "Select a strategy you want to edit": "Choisissez une strategie a modifier",
        "You can only save strategies you have created yourself. Otherwise save it under a new name.": "Vous ne pouvez enregistrer que les strategies que vous avez creees. Sinon, enregistrez-la sous un nouveau nom.",
        "Saves the current strategy under a new name": "Enregistre la strategie actuelle sous un nouveau nom",
        "Ignore Funds changes above threshold in logging (in cents)": "Ignorer les variations de tapis au-dessus du seuil dans les logs (en centimes)",
        "Adjustments for position and pot size": "Ajustements selon la position et la taille du pot",
        "Calling": "Call",
        "Update Graph": "Mettre a jour le graphe",
        "Flop": "Flop",
        "Turn": "Turn",
        "River": "River",
        "Postflop adjustments": "Ajustements postflop",
        "Bluffing": "Bluff",
        "Additional options": "Options supplementaires",
        "Extreme cases": "Cas extremes",
        "Betting and Ranges": "Mises et ranges",
        "Betting sizes": "Tailles de mise",
        "Preflop Range": "Range preflop",
        "Ranges Flop Turn and River:": "Ranges Flop Turn et River :",
        "Use relative equity to make decision instead of absolute equity": "Utiliser l'equite relative pour la decision au lieu de l'equite absolue",
        "Differentiate between call and raise in the reverse sheet": "Distinguer call et raise dans la feuille inverse",
        "Bet and Bluff conditions": "Conditions de mise et de bluff",
        "Flop bluffing": "Bluff au flop",
        "There is a check button": "Il y a un bouton check",
        "HeadsUp (only 1 opponent remains in the game)": "Heads-up (un seul adversaire reste en jeu)",
        "Equity is higher than minimum bluff equity for that stage": "L'equite est superieure a l'equite minimale de bluff pour cette etape",
        "Only bluff in first round of the current stage": "Bluffer uniquement au premier tour de cette etape",
        "Only bluff if no players are ahead in this round (in position)": "Bluffer seulement si aucun joueur n'est a parler apres nous sur ce tour",
        "Add 10% to required equity if opponent raised without initiative": "Ajouter 10 % a l'equite requise si l'adversaire a relance sans initiative",
        "Flop betting": "Mise au flop",
        "Equity is higher than minimum bet equity for that stage": "L'equite est superieure a l'equite minimale de mise pour cette etape",
        "The required raise is to the right of the red betting curve": "La relance requise se situe a droite de la courbe rouge de mise",
        "Don't bet if other player has initiative unless no check button": "Ne pas miser si l'adversaire a l'initiative, sauf s'il n'y a pas de bouton check",
        "Turn bluffing": "Bluff au turn",
        "Don't bluff if other player has initiative": "Ne pas bluffer si l'adversaire a l'initiative",
        "River bluffing": "Bluff a la river",
        "River betting": "Mise a la river",
        "Turn betting": "Mise au turn",
        "Bet Button": "Bouton de mise",
        "Search areas for cards": "Zones de recherche des cartes",
        "Table Cards area": "Zone des cartes du tableau",
        "My Cards area": "Zone de mes cartes",
        "Values": "Valeurs",
        "Game Number": "Numero de partie",
        "All in call value": "Valeur du call all-in",
        "Call value": "Valeur du call",
        "Raise Value": "Valeur de la relance",
        "Current Round Pot value": "Valeur du pot du tour",
        "Total Pot value": "Valeur totale du pot",
        "Players": "Joueurs",
        "Player (0=myself)": "Joueur (0 = moi)",
        "Table size": "Taille de la table",
        "Dealer button search area": "Zone de recherche du bouton dealer",
        "Covered card area (cards upside down)": "Zone des cartes cachees (retournees)",
        "Pot of the player": "Pot du joueur",
        "Player pot area": "Zone du pot du joueur",
        "Player funds area": "Zone du tapis du joueur",
        "Player name area": "Zone du nom du joueur",
        "Cards": "Cartes",
        "Neural Network based recognition for My Cards": "Reconnaissance de mes cartes par reseau neuronal",
        "Right Card Area": "Zone de la carte de droite",
        "Left Card Area": "Zone de la carte de gauche",
        "Images": "Images",
        "Saved": "Enregistre",
        "To save strategies you need to purchase a subscription": "Pour enregistrer des strategies, vous devez acheter un abonnement",
        "There has been a problem and the strategy is not saved. Check if the name is already taken.": "Un probleme est survenu et la strategie n'a pas ete enregistree. Verifiez si le nom est deja pris.",
        "Strategy editor": "Editeur de strategie",
        "Take screenshot": "Prendre une capture",
        "Information": "Information",
        "Error": "Erreur",
        "Screenshots finished": "Captures terminees",
        "Saving screenshots finished.": "Enregistrement des captures termine.",
        "Saving screenshots failed.": "Echec de l'enregistrement des captures.",
        "Loading screenshots failed.": "Echec du chargement des captures.",
        "Not authorized.": "Non autorise.",
        "You can only edit your own tables. Please create a new copy or start with a new blank table": "Vous ne pouvez modifier que vos propres tables. Creez une copie ou partez d'une table vide.",
        "Logging data": "Enregistrement des donnees",
        "Updating charts and work in background": "Mise a jour des graphiques et travail en arriere-plan",
        "***Improving current strategy***": "***Amelioration de la strategie actuelle***",
        "Table not found yet": "Table non trouvee pour le moment",
        "I am back found": "\"Je suis de retour\" detecte",
        "Resume hand": "Reprendre la main",
        "Check for fast fold": "Verification du fold rapide",
        "Get table pots": "Lecture des pots de table",
        "Get bot pot": "Lecture du pot du bot",
        "Get other playsrs' status": "Lecture de l'etat des autres joueurs",
        "Get round number": "Lecture du numero de tour",
        "Get dealer position": "Lecture de la position du donneur",
        "Unable to get pot value": "Impossible de lire la valeur du pot",
        "Unable to get round pot value": "Impossible de lire la valeur du pot du tour",
        "Get my funds": "Lecture de mon tapis",
        "Funds NOT recognised": "Tapis NON reconnu",
        "Get call value": "Lecture de la valeur de call",
        "Get raise value": "Lecture de la valeur de relance",
        "Everything is lost. Last game has been marked.": "Tout est perdu. La derniere partie a ete marquee.",
        "Check if new hand": "Verification d'une nouvelle main",
        "Direct mouse control": "Controle direct de la souris",
        "Fold": "Se coucher",
        "Check": "Check",
        "Call": "Suivre",
        "Bet": "Miser",
        "BetPlus": "Relance",
        "Bet half pot": "Miser demi-pot",
        "Bet pot": "Miser pot",
        "Bet Bluff": "Miser en bluff",
        "Call Deception": "Suivre en deception",
        "Check Deception": "Checker en deception",
    }
}

RUNTIME_PATTERNS = {
    "fr": [
        (re.compile(r"^Cancel \((?P<count>\d+)\)$"), "Annuler ({count})"),
        (re.compile(r"^Execute the (?P<action>.+) and then press OK to continue$"), "Executez {action} puis appuyez sur OK pour continuer"),
        (re.compile(r"^Recommendation: (?P<action>.+)$"), "Recommandation : {action}"),
        (re.compile(r"^Running range Monte Carlo: (?P<count>\d+)$"), "Monte Carlo de range en cours : {count}"),
        (re.compile(r"^Running card Monte Carlo: (?P<count>\d+)$"), "Monte Carlo cartes en cours : {count}"),
        (re.compile(r"^Running native equity: (?P<count>\d+)$"), "Calcul d'equite natif en cours : {count}"),
        (re.compile(r"^Check other players (?P<count>\d+)$"), "Verification des autres joueurs {count}"),
        (re.compile(r"^Check other players funds (?P<count>\d+)$"), "Verification des tapis des autres joueurs {count}"),
        (re.compile(r"^Get player pots of players in game (?P<players>.+)$"), "Lecture des pots joueurs en jeu {players}"),
        (re.compile(r"^New hand: (?P<cards>.+)$"), "Nouvelle main : {cards}"),
        (re.compile(r"^(?P<decision>Fold|Check|Call|Bet|BetPlus|Bet half pot|Bet pot|Bet Bluff|Call Deception|Check Deception)(?P<suffix>.*)$"), "{decision_translated}{suffix}"),
    ]
}

LANGUAGE_NAMES = {
    "en": {
        "en": "English",
        "fr": "French",
    },
    "fr": {
        "en": "Anglais",
        "fr": "Francais",
    },
}


def normalize_language(language: str | None) -> str:
    """Normalize user/config language values."""
    if not language:
        return DEFAULT_LANGUAGE

    language = str(language).strip().lower()
    if language.startswith("fr"):
        return "fr"
    return "en"


def get_language(config=None) -> str:
    """Read the configured UI language."""
    config = config or get_config()
    try:
        return normalize_language(config.config.get("main", "language"))
    except Exception:
        return DEFAULT_LANGUAGE


def get_language_name(code: str, display_language: str | None = None) -> str:
    """Return the localized display name for a language code."""
    code = normalize_language(code)
    display_language = normalize_language(display_language)
    return LANGUAGE_NAMES.get(display_language, LANGUAGE_NAMES[DEFAULT_LANGUAGE]).get(code, code)


def translate_text(text: str, language: str | None = None) -> str:
    """Translate a UI/runtime string when a matching translation exists."""
    if not isinstance(text, str):
        return text

    language = normalize_language(language)
    if language == "en" or not text:
        return text

    translated = TRANSLATIONS.get(language, {}).get(text)
    if translated is not None:
        return translated

    if text.lstrip().startswith("<html"):
        translated_html = text
        for source, target in sorted(TRANSLATIONS.get(language, {}).items(), key=lambda item: len(item[0]), reverse=True):
            if source in translated_html:
                translated_html = translated_html.replace(source, target)
        if translated_html != text:
            return translated_html

    for pattern, template in RUNTIME_PATTERNS.get(language, []):
        match = pattern.match(text)
        if not match:
            continue

        groups = match.groupdict()
        decision = groups.get("decision")
        if decision:
            groups["decision_translated"] = TRANSLATIONS[language].get(decision, decision)
        return template.format(**groups)

    return text


def _remember_original(obj: QtCore.QObject, name: str, value: str) -> str:
    property_name = f"i18n_original_{name}"
    original = obj.property(property_name)
    if original is None:
        obj.setProperty(property_name, value)
        return value
    return original


def _translate_property(obj: QtCore.QObject, name: str, getter_name: str, setter_name: str, language: str) -> None:
    if not hasattr(obj, getter_name) or not hasattr(obj, setter_name):
        return

    try:
        value = getattr(obj, getter_name)()
    except TypeError:
        return

    if not isinstance(value, str):
        return

    original = _remember_original(obj, name, value)
    getattr(obj, setter_name)(translate_text(original, language))


def apply_translations(root: QtCore.QObject, language: str | None = None) -> None:
    """Translate supported widget properties for a window and its children."""
    language = normalize_language(language)
    if root is None:
        return

    widgets = [root]
    if hasattr(root, "findChildren"):
        widgets.extend(root.findChildren(QtCore.QObject))

    for widget in widgets:
        _translate_property(widget, "window_title", "windowTitle", "setWindowTitle", language)
        _translate_property(widget, "tool_tip", "toolTip", "setToolTip", language)
        _translate_property(widget, "status_tip", "statusTip", "setStatusTip", language)
        _translate_property(widget, "whats_this", "whatsThis", "setWhatsThis", language)
        _translate_property(widget, "title", "title", "setTitle", language)

        if isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QTextEdit, QtWidgets.QTextBrowser)):
            pass
        else:
            _translate_property(widget, "text", "text", "setText", language)

        if isinstance(widget, QtWidgets.QTabWidget):
            original_tabs = widget.property("i18n_original_tabs")
            if original_tabs is None:
                original_tabs = [widget.tabText(index) for index in range(widget.count())]
                widget.setProperty("i18n_original_tabs", original_tabs)

            for index, original in enumerate(original_tabs):
                widget.setTabText(index, translate_text(original, language))
