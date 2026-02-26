from django.utils.text import slugify

from allauth.account.signals import user_signed_up

from app.domain.models import Membership, Tenant


def create_default_tenant(request, user, **kwargs):
    name = f"{user.username}'s workspace"
    base_slug = slugify(user.username) or slugify(user.email.split("@")[0])

    # Ensure slug uniqueness
    slug = base_slug
    counter = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    tenant = Tenant.objects.create(name=name, slug=slug)
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.OWNER)
    request.session["active_tenant_id"] = str(tenant.id)


user_signed_up.connect(create_default_tenant)
