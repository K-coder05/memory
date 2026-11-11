from rest_framework.routers import DefaultRouter

from .views import MemoryViewSet

router = DefaultRouter(trailing_slash=False)
router.register("memories", MemoryViewSet, basename="memory")

urlpatterns = router.urls