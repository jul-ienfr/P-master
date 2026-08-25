"""Routes runtime : /status, /runtime-snapshot, /runtime-observation*, /operator-control, timesfm (extrait de src/api/server.py)."""

import asyncio
import json
import logging

from aiohttp import web

logger = logging.getLogger("BotAPI")


class RuntimeRoutesMixin:
    async def handle_get_status(self, request):
        """
        L'interface GUI interroge cette route toutes les secondes.
        Renvoie l'état actuel du bot (en train de jouer, bloqué, ou prêt à être ré-entraîné).
        """
        response_data = {
            "status": "playing",
            "ready_for_training": self.hitl.check_convergence(),
            "collected_samples": self.hitl.annotations_count,
            "target_samples": self.hitl.target_dataset_size,
        }

        if self.runtime_status_provider:
            try:
                runtime = await asyncio.to_thread(self.runtime_status_provider)
                runtime = runtime or {}
                response_data["runtime"] = runtime
                response_data["tracker"] = runtime.get("tracker", {}) or {}
                response_data["gate"] = runtime.get("gate", {}) or {}
                response_data["decision"] = runtime.get("decision", {}) or {}
                response_data["operator"] = runtime.get("operator", {}) or {}
                response_data["health"] = runtime.get("health", {}) or {}
                response_data["active_solver_backend"] = runtime.get(
                    "active_solver_backend", "fallback"
                )
                response_data["degraded_reasons"] = runtime.get("degraded_reasons", []) or []
                response_data["last_success_at"] = runtime.get("last_success_at")
            except Exception as e:
                logger.error(f"Erreur lors de la lecture du runtime status: {e}")
                response_data["runtime"] = {
                    "gate": {
                        "allowed": False,
                        "status": "error",
                        "reasons": [
                            {"code": "RUNTIME_STATUS_ERROR", "message": str(e), "context": {}}
                        ],
                        "action_intent": None,
                    }
                }
                response_data["tracker"] = {}
                response_data["gate"] = response_data["runtime"]["gate"]
                response_data["decision"] = {}
                response_data["operator"] = {}
                response_data["health"] = {}
                response_data["active_solver_backend"] = "fallback"
                response_data["degraded_reasons"] = ["api:runtime_status_error"]
                response_data["last_success_at"] = None

        if self.hitl.is_waiting_for_human and self.hitl.current_issue:
            response_data["status"] = "waiting_for_human"
            response_data["issue"] = {
                "type": self.hitl.current_issue["type"],
                "reason": self.hitl.current_issue["reason"],
                "image_base64": self.hitl.current_issue["image_base64"],
                "width": self.hitl.current_issue["width"],
                "height": self.hitl.current_issue["height"],
            }

        return web.json_response(response_data)

    async def handle_runtime_snapshot(self, request):
        try:
            payload = await self._build_runtime_snapshot_payload_async()
            return web.json_response(payload)
        except Exception as e:
            logger.error(f"Erreur lors de la construction du runtime snapshot: {e}")
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500
            )

    async def handle_runtime_observation(self, request):
        try:
            limit = self._parse_limit(request.query.get("limit"), default=5, maximum=20)
            payload = await asyncio.to_thread(self._build_runtime_observation_payload, limit)
            payload["refreshed_at"] = self._now_iso()
            return web.json_response(payload)
        except Exception as e:
            logger.error(f"Erreur lors de la construction du runtime observation snapshot: {e}")
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500
            )

    async def handle_runtime_observation_export(self, request):
        if self.runtime_observation_exporter is None:
            return web.json_response(
                {
                    "state": "error",
                    "message": "Observation export is unavailable.",
                    "refreshed_at": self._now_iso(),
                },
                status=503,
            )

        try:
            player_limit = self._parse_limit(request.query.get("players"), default=50, maximum=500)
            hand_limit = self._parse_limit(request.query.get("hands"), default=100, maximum=1000)
            payload = (
                self.runtime_observation_exporter(player_limit=player_limit, hand_limit=hand_limit)
                or {}
            )
            return web.Response(
                text=json.dumps(payload, ensure_ascii=True),
                content_type="application/json",
                headers={
                    "Content-Disposition": 'attachment; filename="runtime_observation.json"',
                },
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'export observation: {e}")
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500
            )

    async def handle_operator_control(self, request):
        if self.runtime_operator_handler is None:
            return web.json_response(
                {
                    "state": "error",
                    "message": "Operator controls are unavailable.",
                    "refreshed_at": self._now_iso(),
                },
                status=503,
            )

        try:
            payload = await request.json()
        except Exception as e:
            return web.json_response(
                {
                    "state": "error",
                    "message": f"Invalid operator payload: {e}",
                    "refreshed_at": self._now_iso(),
                },
                status=400,
            )

        if not isinstance(payload, dict):
            return web.json_response(
                {
                    "state": "error",
                    "message": "Operator payload must be a JSON object.",
                    "refreshed_at": self._now_iso(),
                },
                status=400,
            )

        operator_patch = (
            payload.get("operator") if isinstance(payload.get("operator"), dict) else payload
        )
        try:
            await asyncio.to_thread(self.runtime_operator_handler, dict(operator_patch))
            self._invalidate_runtime_snapshot_cache()
            snapshot_payload = await self._build_runtime_snapshot_payload_async(force=True)
            return web.json_response(snapshot_payload)
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des contrôles opérateur: {e}")
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()},
                status=500,
            )

    async def handle_runtime_timesfm_forecast(self, request):
        if self.runtime_timesfm_provider is None:
            return web.json_response(
                {
                    "state": "error",
                    "message": "TimesFM runtime forecasts are disabled.",
                    "refreshed_at": self._now_iso(),
                },
                status=404,
            )

        try:
            metric = str(request.query.get("metric") or "").strip() or None
            raw_horizon = request.query.get("horizon")
            raw_max_context = request.query.get("max_context") or request.query.get("max-context")
            horizon = int(raw_horizon) if raw_horizon not in (None, "") else None
            max_context = int(raw_max_context) if raw_max_context not in (None, "") else None
            history_path = (
                str(
                    request.query.get("history_path") or request.query.get("history-path") or ""
                ).strip()
                or None
            )
            payload = await asyncio.to_thread(
                self.runtime_timesfm_provider,
                metric=metric,
                horizon=horizon,
                max_context=max_context,
                history_path=history_path,
            )
            payload = dict(payload or {})
            payload.setdefault("refreshed_at", self._now_iso())
            return web.json_response(payload)
        except ValueError as e:
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=400
            )
        except RuntimeError as e:
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=503
            )
        except Exception as e:
            logger.error(f"Erreur lors du forecast runtime TimesFM: {e}")
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500
            )
