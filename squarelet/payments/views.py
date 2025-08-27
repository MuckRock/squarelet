# Django
from django.views.generic.base import TemplateView

# Squarelet
from squarelet.organizations.models import Plan, Organization


class SunlightResearchPlansView(TemplateView):
    template_name = "payments/sunlight-research-plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Fetch Sunlight research plans
        sunlight_plans = list(Plan.objects.filter(slug__startswith="src-", wix=True))
        context["sunlight_plans"] = sunlight_plans
        
        # 2. Fetch user subscription information
        # 3. Fetch organization subscription information
        #    for each organization the user administers
        existing_subscriptions = []
        
        if self.request.user.is_authenticated:
            # Check user's individual organization
            individual_org = self.request.user.individual_organization
            individual_subscriptions = individual_org.subscriptions.filter(
                plan__slug__startswith="src-", 
                plan__wix=True,
                cancelled=False
            ).select_related("plan")
            
            for subscription in individual_subscriptions:
                existing_subscriptions.append((subscription.plan, individual_org))
            
            # Check organizations where user is admin
            admin_orgs = Organization.objects.filter(
                users=self.request.user,
                memberships__admin=True,
                individual=False
            ).distinct()
            
            for org in admin_orgs:
                org_subscriptions = org.subscriptions.filter(
                    plan__slug__startswith="src-",
                    plan__wix=True,
                    cancelled=False
                ).select_related("plan")
                
                for subscription in org_subscriptions:
                    existing_subscriptions.append((subscription.plan, org))
        
        context["existing_subscriptions"] = existing_subscriptions
        
        return context