from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .catalog import SkillCatalog, validate_allowed_tools
from .model import ActiveSkill, Skill, SkillValidationError


@dataclass(frozen=True)
class SkillRefresh:
    changed: bool = False
    removed: tuple[str, ...] = ()


class SkillRuntime:
    def __init__(
        self,
        catalog: SkillCatalog,
        ordinary_tools: Iterable[str] = (),
    ) -> None:
        self._catalog = catalog
        self._ordinary_tools = frozenset(ordinary_tools)
        self._active: dict[str, ActiveSkill] = {}
        self._validate_catalog(catalog)

    @property
    def catalog(self) -> SkillCatalog:
        return self._catalog

    def available_prompt(self) -> str:
        lines = [
            f"- `{skill.metadata.name}`: {skill.metadata.description}"
            for skill in self._catalog.effective()
        ]
        return "\n".join(lines)

    def active_skills(self) -> tuple[ActiveSkill, ...]:
        return tuple(self._active.values())

    def activate_inline(self, name: str, argument: str) -> ActiveSkill:
        skill = self._require(name)
        candidate = self._render(skill, argument)
        self._ensure_model_compatible(candidate, replace=name)
        self._active.pop(name, None)
        self._active[name] = candidate
        return candidate

    def prepare_fork(self, name: str, argument: str) -> ActiveSkill:
        return self._render(self._require(name), argument)

    def clear(self) -> None:
        self._active.clear()

    def active_environment(self) -> str:
        if not self._active:
            return ""
        blocks = ["# 已激活 Skill"]
        for skill in self._active.values():
            blocks.append(f"## {skill.name}\n{skill.instruction}")
        return "\n\n".join(blocks)

    def ordinary_allowed_tools(self) -> frozenset[str] | None:
        if not self._active:
            return None
        return frozenset().union(
            *(skill.allowed_tools for skill in self._active.values())
        )

    def requested_model(self) -> str | None:
        models = {skill.model for skill in self._active.values() if skill.model}
        return next(iter(models), None)

    def refresh(self) -> SkillRefresh:
        if not self._catalog.has_changed():
            return SkillRefresh()
        updated = self._catalog.reloaded()
        self._validate_catalog(updated)
        active: dict[str, ActiveSkill] = {}
        removed: list[str] = []
        for name, previous in self._active.items():
            skill = updated.get(name)
            if skill is None:
                removed.append(name)
                continue
            try:
                candidate = self._render(skill, previous.argument)
                self._ensure_model_compatible(candidate, existing=active)
            except SkillValidationError:
                removed.append(name)
                continue
            active[name] = candidate
        self._catalog = updated
        self._active = active
        return SkillRefresh(True, tuple(removed))

    def _require(self, name: str) -> Skill:
        skill = self._catalog.get(name)
        if skill is None:
            raise SkillValidationError(f"未找到 Skill: {name}")
        return skill

    def _render(self, skill: Skill, argument: str) -> ActiveSkill:
        return ActiveSkill(
            name=skill.metadata.name,
            argument=argument,
            instruction=skill.load_instruction(argument),
            allowed_tools=skill.metadata.allowed_tools,
            model=skill.metadata.model,
        )

    def _ensure_model_compatible(
        self,
        candidate: ActiveSkill,
        *,
        replace: str | None = None,
        existing: dict[str, ActiveSkill] | None = None,
    ) -> None:
        active = self._active if existing is None else existing
        models = {
            skill.model
            for name, skill in active.items()
            if name != replace and skill.model
        }
        if candidate.model and models and candidate.model not in models:
            conflict = next(iter(models))
            raise SkillValidationError(
                f"Skill {candidate.name} 指定模型 {candidate.model}，"
                f"与已激活模型 {conflict} 冲突"
            )

    def _validate_catalog(self, catalog: SkillCatalog) -> None:
        if self._ordinary_tools:
            try:
                validate_allowed_tools(catalog.effective(), self._ordinary_tools)
            except Exception as exc:
                raise SkillValidationError(str(exc)) from exc


__all__ = ["SkillRefresh", "SkillRuntime"]
