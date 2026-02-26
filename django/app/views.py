from rest_framework.response import Response
from rest_framework.views import APIView

from app.sandbox.policies import CHECK_README
from app.sandbox.runner import SandboxRunner


class RunPolicyView(APIView):
    def post(self, request):
        context = request.data
        result = SandboxRunner().run(CHECK_README, context)
        return Response(result)
