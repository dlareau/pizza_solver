from allauth.account.adapter import DefaultAccountAdapter


class ProfileRedirectAdapter(DefaultAccountAdapter):
    def get_signup_redirect_url(self, request):
        return '/profile/edit/?setup=1'
