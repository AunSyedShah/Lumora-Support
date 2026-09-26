"""
Catalog API: departments, categories, subcategories and SLA rules.

Any logged-in user can read. Only administrators can create / update / delete.
Resources are addressed by their code (e.g. /departments/BILLING) because codes are
the stable IDs shared with the GenAI prompt and the validation rules.
"""

from django.db.models import Prefetch, ProtectedError
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from accounts.auth import require_role
from accounts.models import User
from accounts.schemas import ErrorOut

from .models import Category, Department, Product, SLARule, Subcategory
from .schemas import (
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    DepartmentIn,
    DepartmentOut,
    DepartmentUpdate,
    ProductIn,
    ProductOut,
    ProductUpdate,
    SLARuleIn,
    SLARuleOut,
    SLARuleUpdate,
    SubcategoryIn,
    SubcategoryOut,
    SubcategoryUpdate,
    TaxonomyOut,
)

router = Router(tags=["Catalog"])

ADMIN = User.Role.ADMIN


def _department(code):
    return get_object_or_404(Department, code=code)


def _category(code):
    return get_object_or_404(Category, code=code)


def _check_unique_code(model, code):
    if model.objects.filter(code=code).exists():
        raise HttpError(409, f"{model.__name__} with code '{code}' already exists.")


def _delete(obj):
    """Delete, or return 409 if other records still point to it."""
    try:
        obj.delete()
    except ProtectedError:
        raise HttpError(
            409, "Still in use by other records. Deactivate it (is_active=false) instead."
        )


def _clean_keywords(keywords):
    """Lower-case, trim and de-duplicate keyword phrases (matching is case-insensitive)."""
    return list(dict.fromkeys(k.strip().lower() for k in keywords if k.strip()))


def _apply(obj, data):
    """Copy only the fields the client actually sent (PATCH semantics)."""
    for field, value in data.items():
        setattr(obj, field, value)
    obj.save()
    return obj


# ---------------- Taxonomy ----------------


@router.get("/taxonomy", response=TaxonomyOut)
def taxonomy(request):
    """Active departments + categories with nested subcategories, in one call."""
    active_subcategories = Subcategory.objects.filter(is_active=True).select_related(
        "department", "category__default_department"
    )
    categories = (
        Category.objects.filter(is_active=True)
        .select_related("default_department")
        .prefetch_related(Prefetch("subcategories", queryset=active_subcategories))
    )
    return {
        "departments": Department.objects.filter(is_active=True),
        "categories": categories,
    }


# ---------------- Departments ----------------


@router.get("/departments", response=list[DepartmentOut])
def list_departments(request, active_only: bool = False):
    qs = Department.objects.all()
    return qs.filter(is_active=True) if active_only else qs


@router.get("/departments/{code}", response=DepartmentOut)
def get_department(request, code: str):
    return _department(code)


@router.post("/departments", response={201: DepartmentOut, 409: ErrorOut})
def create_department(request, data: DepartmentIn):
    require_role(request, ADMIN)
    _check_unique_code(Department, data.code)
    return 201, Department.objects.create(**data.model_dump())


@router.patch("/departments/{code}", response=DepartmentOut)
def update_department(request, code: str, data: DepartmentUpdate):
    require_role(request, ADMIN)
    return _apply(_department(code), data.model_dump(exclude_unset=True))


@router.delete("/departments/{code}", response={204: None, 409: ErrorOut})
def delete_department(request, code: str):
    require_role(request, ADMIN)
    _delete(_department(code))
    return 204, None


# ---------------- Categories ----------------


@router.get("/categories", response=list[CategoryOut])
def list_categories(request, active_only: bool = False):
    qs = Category.objects.select_related("default_department")
    return qs.filter(is_active=True) if active_only else qs


@router.get("/categories/{code}", response=CategoryOut)
def get_category(request, code: str):
    return _category(code)


@router.post("/categories", response={201: CategoryOut, 404: ErrorOut, 409: ErrorOut})
def create_category(request, data: CategoryIn):
    require_role(request, ADMIN)
    _check_unique_code(Category, data.code)
    fields = data.model_dump()
    fields["default_department"] = _department(data.default_department)
    return 201, Category.objects.create(**fields)


@router.patch("/categories/{code}", response=CategoryOut)
def update_category(request, code: str, data: CategoryUpdate):
    require_role(request, ADMIN)
    fields = data.model_dump(exclude_unset=True)
    if "default_department" in fields:
        fields["default_department"] = _department(fields["default_department"])
    return _apply(_category(code), fields)


@router.delete("/categories/{code}", response={204: None, 409: ErrorOut})
def delete_category(request, code: str):
    require_role(request, ADMIN)
    _delete(_category(code))
    return 204, None


# ---------------- Subcategories ----------------


@router.get("/subcategories", response=list[SubcategoryOut])
def list_subcategories(request, category: str | None = None, active_only: bool = False):
    qs = Subcategory.objects.select_related("category__default_department", "department")
    if category:
        qs = qs.filter(category__code=category)
    return qs.filter(is_active=True) if active_only else qs


@router.get("/subcategories/{code}", response=SubcategoryOut)
def get_subcategory(request, code: str):
    return get_object_or_404(Subcategory, code=code)


@router.post("/subcategories", response={201: SubcategoryOut, 404: ErrorOut, 409: ErrorOut})
def create_subcategory(request, data: SubcategoryIn):
    require_role(request, ADMIN)
    _check_unique_code(Subcategory, data.code)
    fields = data.model_dump()
    fields["keywords"] = _clean_keywords(data.keywords)
    fields["takes_precedence_over"] = [c.upper() for c in data.takes_precedence_over]
    fields["category"] = _category(data.category)
    fields["department"] = _department(data.department) if data.department else None
    return 201, Subcategory.objects.create(**fields)


@router.patch("/subcategories/{code}", response=SubcategoryOut)
def update_subcategory(request, code: str, data: SubcategoryUpdate):
    require_role(request, ADMIN)
    fields = data.model_dump(exclude_unset=True)
    if fields.get("keywords") is not None:
        fields["keywords"] = _clean_keywords(fields["keywords"])
    if fields.get("takes_precedence_over") is not None:
        fields["takes_precedence_over"] = [c.upper() for c in fields["takes_precedence_over"]]
    if "category" in fields:
        fields["category"] = _category(fields["category"])
    if "department" in fields:
        fields["department"] = _department(fields["department"]) if fields["department"] else None
    return _apply(get_object_or_404(Subcategory, code=code), fields)


@router.delete("/subcategories/{code}", response={204: None, 409: ErrorOut})
def delete_subcategory(request, code: str):
    require_role(request, ADMIN)
    _delete(get_object_or_404(Subcategory, code=code))
    return 204, None


# ---------------- Products ----------------


@router.get("/products", response=list[ProductOut])
def list_products(request, active_only: bool = False):
    qs = Product.objects.all()
    return qs.filter(is_active=True) if active_only else qs


@router.post("/products", response={201: ProductOut, 409: ErrorOut})
def create_product(request, data: ProductIn):
    require_role(request, ADMIN)
    _check_unique_code(Product, data.code)
    if Product.objects.filter(name__iexact=data.name).exists():
        raise HttpError(409, f"A product named '{data.name}' already exists.")
    return 201, Product.objects.create(**data.model_dump())


@router.patch("/products/{code}", response=ProductOut)
def update_product(request, code: str, data: ProductUpdate):
    require_role(request, ADMIN)
    return _apply(get_object_or_404(Product, code=code), data.model_dump(exclude_unset=True))


# ---------------- SLA rules ----------------


@router.get("/sla-rules", response=list[SLARuleOut])
def list_sla_rules(request):
    return SLARule.objects.all()


@router.post("/sla-rules", response={201: SLARuleOut, 409: ErrorOut})
def create_sla_rule(request, data: SLARuleIn):
    require_role(request, ADMIN)
    if SLARule.objects.filter(priority=data.priority).exists():
        raise HttpError(409, f"An SLA rule for {data.priority} already exists.")
    return 201, SLARule.objects.create(**data.model_dump())


@router.patch("/sla-rules/{priority}", response=SLARuleOut)
def update_sla_rule(request, priority: str, data: SLARuleUpdate):
    require_role(request, ADMIN)
    rule = get_object_or_404(SLARule, priority=priority)
    return _apply(rule, data.model_dump(exclude_unset=True))
