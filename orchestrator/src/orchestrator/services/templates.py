from __future__ import annotations

from orchestrator.domain.models import (
    CreateTemplateRequest,
    Template,
    TemplateListParams,
    TemplateListResponse,
    UpdateTemplateRequest,
)
from orchestrator.infra.repositories import TemplateRepository
from orchestrator.utils import short_id, utcnow


class TemplateService:
    def __init__(self, repository: TemplateRepository) -> None:
        self.repository = repository

    def create_template(self, req: CreateTemplateRequest) -> Template:
        now = utcnow()
        template = Template.model_validate(
            req.model_dump() | {"id": req.id or short_id(), "created_at": now, "updated_at": now}
        )
        try:
            self.repository.get(template.id)
        except Exception:
            pass
        else:
            raise ValueError(f"template with ID {template.id} already exists")
        return self.repository.save(template)

    def get_template(self, template_id: str) -> Template:
        return self.repository.get(template_id)

    def list_templates(self, params: TemplateListParams) -> TemplateListResponse:
        templates = self.repository.list()
        filtered = []
        for template in templates:
            if params.name and params.name.lower() not in template.name.lower():
                continue
            if params.user_id and template.metadata.get("user_id") != params.user_id:
                continue
            filtered.append(template)
        filtered.sort(key=lambda item: item.created_at, reverse=True)
        return TemplateListResponse.from_items(filtered, params.page, params.page_size)

    def update_template(self, template_id: str, req: UpdateTemplateRequest) -> Template:
        template = self.repository.get(template_id)
        updates = req.model_dump(exclude_none=True)
        updated = template.model_copy(update={**updates, "updated_at": utcnow()})
        return self.repository.save(updated)

    def delete_template(self, template_id: str) -> None:
        self.repository.get(template_id)
        self.repository.delete(template_id)
