# Pont HID — crochets d'extension de l'injection d'entrées

> **Statut : crochet prêt, implémentation matérielle reportée.** Le switch
> `bot.humanization.input_backend = "hid"` lève volontairement une erreur
> explicite au boot (`ValueError` pointant vers ce document) : jamais de
> fallback silencieux. L'implémentation future d'un `SerialHidBackend`
> n'exigera **aucune** modification ailleurs que dans
> `src/bot/action_controller.py` (nouvelle classe backend) + cette doc.

## Contrat à respecter : `InputBackend`

Défini dans `src/bot/action_controller.py` :

```python
class InputBackend(Protocol):
    async def move_to(self, x: int, y: int) -> None: ...
    async def press(self, vk: int) -> None: ...
    async def release(self, vk: int) -> None: ...
    async def type_char(self, ch: str) -> bool: ...   # shift-state géré, False si non mappé
```

`Win32Backend` (défaut) encapsule déjà `SetCursorPos` / `mouse_event` /
`keybd_event`. Les primitives absolues (`mouse_down_abs`, `mouse_up_abs`,
`get_cursor_pos`) sont des extensions concrètes utilisées par le clic.

Pour brancher le HID plus tard :

1. écrire `SerialHidBackend(InputBackend)` dans `action_controller.py`
   (liaison série via `pyserial`, mêmes méthodes async) ;
2. étendre la sélection dans `HumanizationProfile.from_config`
   (`input_backend == "hid"` → instancier le backend au lieu de lever) ;
3. rien d'autre : `ActionController`, gate_flow et la boucle runtime ne
   connaissent que le protocole.

## Solutions matérielles candidates

### 1. Arduino Pro Micro / Leonardo (~5 €) — recommandation

- Émulation USB HID native (ATmega32U4) : la VM voit un vrai clavier/souris.
- Liaison série COM depuis l'hôte (baud 115200 suffisant).
- Sketch côté carte : parser les trames et injecter via la lib `Keyboard.h` /
  `Mouse.h`.
- Limite : débit et pas de retour d'état riche ; suffisant pour move/click/type.

### 2. KMBox / KMBox Net

- Boîtier dédié plug-and-play, liaison réseau (KMBox Net) ou USB.
- Plus cher (~30–60 €), latence réseau faible, API texte déjà documentée par
  le fournisseur.
- Intérêt : pas de sketch à maintenir ; protocole propriétaire simple.

## Protocole série cible (esquisse pour le sketch Arduino)

Trames ASCII terminées par `\n`, checksum XOR sur les champs :

```
M,<x>,<y>,<ck>\n        # move absolu écran
P,<vk>,<ck>\n           # press touche / bouton (convention vk Win32)
R,<vk>,<ck>\n           # release
T,<charcode>,<shift>,<ck>\n   # frappe caractère complète
```

- `<ck>` = XOR des octets précédents de la trame, en hexadécimal.
- Accusé de réception `OK\n` / `ERR,<raison>\n` ; timeout hôte 50 ms puis retry.
- Le mapping caractère → (vk, shift) reste **côté hôte** (`VkKeyScanEx`) afin
  que le firmware reste agnostique du layout.

## Contrainte VirtualBox

Passer-through USB de l'Arduino vers la VM :
`Périphériques → USB → attacher [Arduino Pro Micro]` (filtre USB permanent
recommandé). Le port COM côté hôte disparaît une fois attaché à la VM : faire
parler le backend via un TCP→COM bridge (ex. `socat`/`com2tcp`) si l'hôte doit
garder la main, sinon exécuter le bot dans la VM avec le port natif.
