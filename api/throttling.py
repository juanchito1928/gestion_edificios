from rest_framework.throttling import SimpleRateThrottle


class EdificioRateThrottle(SimpleRateThrottle):
    scope = 'edificio'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        edificio_id = getattr(getattr(request.user, 'perfil', None), 'edificio_id', None)
        if not edificio_id:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': f"edificio_{edificio_id}",
        }