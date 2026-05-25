from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.catalog.schema import validate_identifier, validate_mapping_keys


class RequiredInputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    description: str | None = None


class RecipeScatterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    item: str
    over: str

    @field_validator("id", "item")
    @classmethod
    def validate_scatter_ids(cls, value: str) -> str:
        validate_identifier(value, "recipe scatter identifier")
        return value


class RecipeStepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: str
    optional: bool = False
    scatter: RecipeScatterSpec | None = None
    allowed_tools: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_step_id(cls, value: str) -> str:
        validate_identifier(value, "recipe step id")
        return value

    @field_validator("allowed_tools")
    @classmethod
    def validate_allowed_tools(cls, value: list[str]) -> list[str]:
        for tool_id in value:
            validate_identifier(tool_id, "allowed tool id")
        return value


class RecipeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    required_inputs: dict[str, RequiredInputSpec] = Field(default_factory=dict)
    steps: list[RecipeStepSpec] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_recipe_id(cls, value: str) -> str:
        validate_identifier(value, "recipe id")
        return value

    @field_validator("required_inputs")
    @classmethod
    def validate_required_input_names(
        cls,
        value: dict[str, RequiredInputSpec],
    ) -> dict[str, RequiredInputSpec]:
        validate_mapping_keys(value, "recipe required input")
        return value

    @model_validator(mode="after")
    def validate_steps(self):
        seen_steps = set()
        for step in self.steps:
            if step.id in seen_steps:
                raise ValueError(f"duplicate recipe step id: {step.id}")
            seen_steps.add(step.id)

            if not step.allowed_tools:
                raise ValueError(f"recipe step '{step.id}' must allow at least one tool")

        return self

    def step_by_id(self, step_id: str) -> RecipeStepSpec:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"unknown recipe step: {step_id}")
