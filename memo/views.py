"""View layer adapter. Templates contain presentation, never database queries."""


def render(request, template, context, status_code=200):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name=template,
        context={**context, 'token': request.app.state.token},
        status_code=status_code,
    )
