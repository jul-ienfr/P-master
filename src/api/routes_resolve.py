"""Route HITL : /resolve (extrait de src/api/server.py)."""
import logging

from aiohttp import web

logger = logging.getLogger("BotAPI")


class ResolveRoutesMixin:
    async def handle_resolve(self, request):
        """
        L'interface GUI envoie la réponse de l'utilisateur (les Bounding Boxes).
        Le bot enregistre la réponse et reprend la partie.
        """
        try:
            data = await request.json()
            boxes = data.get("boxes", [])
            
            if not boxes:
                return web.json_response({"error": "Aucune boîte fournie."}, status=400)
                
            if not self.hitl.is_waiting_for_human:
                return web.json_response({"error": "Le bot ne demande aucune intervention humaine actuellement."}, status=400)

            # Transmet la réponse à la logique HITL qui va débloquer le bot
            self.hitl.resolve_human_intervention(boxes)
            
            return web.json_response({"success": True, "message": "Intervention enregistrée. Le bot reprend la partie."})
            
        except Exception as e:
            logger.error(f"Erreur API lors de la résolution HITL : {e}")
            return web.json_response({"error": str(e)}, status=500)

