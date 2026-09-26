from ninja import ModelSchema, Schema
from pydantic import Field

from .models import Category, Department, Priority, Product, SLARule, Subcategory

# ---------- Departments ----------


class DepartmentOut(ModelSchema):
    class Meta:
        model = Department
        fields = ["id", "code", "name", "description", "is_active"]


class DepartmentIn(Schema):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str = ""
    is_active: bool = True


class DepartmentUpdate(Schema):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


# ---------- Categories ----------


class CategoryOut(Schema):
    id: int
    code: str
    name: str
    description: str
    default_department: str = Field(alias="default_department.code")
    is_active: bool


class CategoryIn(Schema):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str = ""
    default_department: str  # department code
    is_active: bool = True


class CategoryUpdate(Schema):
    name: str | None = None
    description: str | None = None
    default_department: str | None = None
    is_active: bool | None = None


# ---------- Subcategories ----------


class SubcategoryOut(Schema):
    id: int
    code: str
    name: str
    description: str
    category: str = Field(alias="category.code")
    department: str | None = Field(None, alias="department.code")  # explicit override
    routed_department: str = Field(alias="routed_department.code")  # effective department
    keywords: list[str]
    is_fallback: bool
    takes_precedence_over: list[str]
    is_active: bool


class SubcategoryIn(Schema):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str = ""
    category: str  # category code
    department: str | None = None  # department code, optional override
    keywords: list[str] = []
    is_fallback: bool = False
    takes_precedence_over: list[str] = []  # subcategory codes
    is_active: bool = True


class SubcategoryUpdate(Schema):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    department: str | None = None
    keywords: list[str] | None = None
    is_fallback: bool | None = None
    takes_precedence_over: list[str] | None = None
    is_active: bool | None = None


# ---------- Products ----------


class ProductOut(Schema):
    id: int
    code: str
    name: str
    kind: str
    price: float
    is_active: bool


class ProductIn(Schema):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    kind: Product.Kind = Product.Kind.DEVICE
    price: float = Field(ge=0)
    is_active: bool = True


class ProductUpdate(Schema):
    name: str | None = None
    price: float | None = Field(None, ge=0)
    is_active: bool | None = None


# ---------- SLA rules ----------


class SLARuleOut(ModelSchema):
    class Meta:
        model = SLARule
        fields = ["id", "priority", "response_hours", "resolution_hours", "at_risk_percent"]


class SLARuleIn(Schema):
    priority: Priority
    response_hours: int = Field(gt=0)
    resolution_hours: int = Field(gt=0)
    at_risk_percent: int = Field(75, ge=1, le=100)


class SLARuleUpdate(Schema):
    response_hours: int | None = Field(None, gt=0)
    resolution_hours: int | None = Field(None, gt=0)
    at_risk_percent: int | None = Field(None, ge=1, le=100)


# ---------- Taxonomy (read-only, used by the GenAI prompt builder) ----------


class TaxonomySubcategory(Schema):
    code: str
    name: str
    department: str = Field(alias="routed_department.code")


class TaxonomyCategory(Schema):
    code: str
    name: str
    default_department: str = Field(alias="default_department.code")
    subcategories: list[TaxonomySubcategory]


class TaxonomyOut(Schema):
    departments: list[DepartmentOut]
    categories: list[TaxonomyCategory]
