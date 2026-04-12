from __future__ import annotations

import re
from typing import Generic, TypeVar

from kubernetes.client import ApiException

from orchestrator.domain.models import Pool, Template, Webhook
from orchestrator.infra.kubernetes import KubernetesGateway

ModelT = TypeVar("ModelT")

_LABEL_ILLEGAL_RE = re.compile(r"[^a-zA-Z0-9._-]")
_LABEL_MAX_LEN = 63


def _sanitize_label_value(value: str) -> str:
    """将任意字符串转为合法的 K8s label value。

    - 非法字符（非 [a-zA-Z0-9._-]）替换为 ``_``
    - 首尾非字母数字字符去除（K8s 要求首尾为字母或数字）
    - 截断至 63 字符
    """
    sanitized = _LABEL_ILLEGAL_RE.sub("_", value)
    sanitized = sanitized.strip("._-")
    return sanitized[:_LABEL_MAX_LEN]


class _ConfigMapRepository(Generic[ModelT]):
    prefix = ""
    payload_key = ""
    base_selector = ""

    def __init__(self, gateway: KubernetesGateway) -> None:
        self.gateway = gateway

    def _name(self, identifier: str) -> str:
        return f"{self.prefix}-{identifier}"

    def _save_payload(self, identifier: str, payload: dict, labels: dict[str, str], annotations: dict[str, str] | None = None) -> None:
        self.gateway.create_or_update_json_configmap(
            name=self._name(identifier),
            labels=labels,
            payload_key=self.payload_key,
            payload=payload,
            annotations=annotations,
        )

    def _get_payload(self, identifier: str) -> tuple[object, dict]:
        return self.gateway.get_json_configmap(self._name(identifier), self.payload_key)

    def _list_payloads(self, selector: str | None = None) -> list[tuple[object, dict]]:
        return self.gateway.list_json_configmaps(
            label_selector=selector or self.base_selector,
            payload_key=self.payload_key,
        )

    def _delete_payload(self, identifier: str) -> None:
        self.gateway.delete_configmap(self._name(identifier))


class TemplateRepository(_ConfigMapRepository[Template]):
    prefix = "template"
    payload_key = "template.json"
    base_selector = "app=litterbox,component=template"

    def save(self, template: Template) -> Template:
        self._save_payload(
            template.id,
            template.model_dump(mode="json"),
            {"app": "litterbox", "component": "template"},
            annotations={"litterbox.io/updated-at": template.updated_at.isoformat()},
        )
        return template

    def get(self, template_id: str) -> Template:
        cm, payload = self._get_payload(template_id)
        payload["created_at"] = cm.metadata.creation_timestamp
        updated = (cm.metadata.annotations or {}).get("litterbox.io/updated-at")
        payload["updated_at"] = updated or cm.metadata.creation_timestamp
        return Template.model_validate(payload)

    def list(self) -> list[Template]:
        templates: list[Template] = []
        for cm, payload in self._list_payloads():
            try:
                payload["created_at"] = cm.metadata.creation_timestamp
                updated = (cm.metadata.annotations or {}).get("litterbox.io/updated-at")
                payload["updated_at"] = updated or cm.metadata.creation_timestamp
                templates.append(Template.model_validate(payload))
            except Exception:
                continue
        return templates

    def delete(self, template_id: str) -> None:
        self._delete_payload(template_id)


class PoolRepository(_ConfigMapRepository[Pool]):
    prefix = "pool"
    payload_key = "pool.json"
    base_selector = "app=litterbox,component=pool"

    def save(self, pool: Pool) -> Pool:
        self._save_payload(
            pool.template_id,
            pool.model_dump(mode="json"),
            {
                "app": "litterbox",
                "component": "pool",
                "litterbox.io/template-id": pool.template_id,
            },
        )
        return pool

    def get(self, template_id: str) -> Pool | None:
        try:
            _, payload = self._get_payload(template_id)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise
        return Pool.model_validate(payload)

    def list(self) -> list[Pool]:
        pools: list[Pool] = []
        for _, payload in self._list_payloads():
            try:
                pools.append(Pool.model_validate(payload))
            except Exception:
                continue
        return pools

    def delete(self, template_id: str) -> None:
        self._delete_payload(template_id)


class WebhookRepository(_ConfigMapRepository[Webhook]):
    prefix = "webhook"
    payload_key = "webhook.json"
    base_selector = "app=litterbox,component=webhook"

    def save(self, webhook: Webhook) -> Webhook:
        self._save_payload(
            webhook.id,
            webhook.model_dump(mode="json"),
            {
                "app": "litterbox",
                "component": "webhook",
                "litterbox.io/user-id": _sanitize_label_value(webhook.user_id),
            },
        )
        return webhook

    def get(self, webhook_id: str) -> Webhook:
        _, payload = self._get_payload(webhook_id)
        return Webhook.model_validate(payload)

    def list(self, user_id: str = "") -> list[Webhook]:
        selector = self.base_selector
        if user_id:
            selector += f",litterbox.io/user-id={_sanitize_label_value(user_id)}"
        webhooks: list[Webhook] = []
        for _, payload in self._list_payloads(selector):
            try:
                webhooks.append(Webhook.model_validate(payload))
            except Exception:
                continue
        return webhooks

    def delete(self, webhook_id: str) -> None:
        self._delete_payload(webhook_id)
