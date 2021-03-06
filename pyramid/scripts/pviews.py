import optparse
import sys

from pyramid.interfaces import IMultiView
from pyramid.paster import bootstrap

def main(argv=sys.argv, quiet=False):
    command = PViewsCommand(argv, quiet)
    command.run()

class PViewsCommand(object):
    """Print, for a given URL, the views that might match. Underneath each
    potentially matching route, list the predicates required. Underneath
    each route+predicate set, print each view that might match and its
    predicates.

    This command accepts two positional arguments:

    ``config_uri`` -- specifies the PasteDeploy config file to use for the
    interactive shell. The format is ``inifile#name``. If the name is left
    off, ``main`` will be assumed.

    ``url`` -- specifies the URL that will be used to find matching views.

    Example::

        $ proutes myapp.ini#main url

    """
    summary = "Print all views in an application that might match a URL"
    stdout = sys.stdout

    parser = optparse.OptionParser()

    bootstrap = (bootstrap,) # testing

    def __init__(self, argv, quiet=False):
        self.quiet = quiet
        self.options, self.args = self.parser.parse_args(argv[1:])

    def out(self, msg): # pragma: no cover
        if not self.quiet:
            print(msg)
    
    def _find_multi_routes(self, mapper, request):
        infos = []
        path = request.environ['PATH_INFO']
        # find all routes that match path, regardless of predicates
        for route in mapper.get_routes():
            match = route.match(path)
            if match is not None:
                info = {'match':match, 'route':route}
                infos.append(info)
        return infos

    def _find_view(self, url, registry):
        """
        Accept ``url`` and ``registry``; create a :term:`request` and
        find a :app:`Pyramid` view based on introspection of :term:`view
        configuration` within the application registry; return the view.
        """
        from zope.interface import providedBy
        from zope.interface import implementer
        from pyramid.interfaces import IRequest
        from pyramid.interfaces import IRootFactory
        from pyramid.interfaces import IRouteRequest
        from pyramid.interfaces import IRequestFactory
        from pyramid.interfaces import IRoutesMapper
        from pyramid.interfaces import IView
        from pyramid.interfaces import IViewClassifier
        from pyramid.interfaces import ITraverser
        from pyramid.request import Request
        from pyramid.traversal import DefaultRootFactory
        from pyramid.traversal import ResourceTreeTraverser

        q = registry.queryUtility
        root_factory = q(IRootFactory, default=DefaultRootFactory)
        routes_mapper = q(IRoutesMapper)
        request_factory = q(IRequestFactory, default=Request)

        adapters = registry.adapters
        request = None

        @implementer(IMultiView)
        class RoutesMultiView(object):

            def __init__(self, infos, context_iface, root_factory, request):
                self.views = []
                for info in infos:
                    match, route = info['match'], info['route']
                    if route is not None:
                        request_iface = registry.queryUtility(
                            IRouteRequest,
                            name=route.name,
                            default=IRequest)
                        view = adapters.lookup(
                            (IViewClassifier, request_iface, context_iface),
                            IView, name='', default=None)
                        if view is None:
                            continue
                        view.__request_attrs__ = {}
                        view.__request_attrs__['matchdict'] = match
                        view.__request_attrs__['matched_route'] = route
                        root_factory = route.factory or root_factory
                        root = root_factory(request)
                        traverser = adapters.queryAdapter(root, ITraverser)
                        if traverser is None:
                            traverser = ResourceTreeTraverser(root)
                        tdict = traverser(request)
                        view.__request_attrs__.update(tdict)
                        if not hasattr(view, '__view_attr__'):
                            view.__view_attr__ = ''
                        self.views.append((None, view, None))


        # create the request
        environ = {
            'wsgi.url_scheme':'http',
            'SERVER_NAME':'localhost',
            'SERVER_PORT':'8080',
            'REQUEST_METHOD':'GET',
            'PATH_INFO':url,
            }
        request = request_factory(environ)
        context = None
        routes_multiview = None
        attrs = request.__dict__
        attrs['registry'] = registry
        request_iface = IRequest

        # find the root object
        if routes_mapper is not None:
            infos = self._find_multi_routes(routes_mapper, request)
            if len(infos) == 1:
                info = infos[0]
                match, route = info['match'], info['route']
                if route is not None:
                    attrs['matchdict'] = match
                    attrs['matched_route'] = route
                    request.environ['bfg.routes.matchdict'] = match
                    request_iface = registry.queryUtility(
                        IRouteRequest,
                        name=route.name,
                        default=IRequest)
                    root_factory = route.factory or root_factory
            if len(infos) > 1:
                routes_multiview = infos

        root = root_factory(request)
        attrs['root'] = root

        # find a context
        traverser = adapters.queryAdapter(root, ITraverser)
        if traverser is None:
            traverser = ResourceTreeTraverser(root)
        tdict = traverser(request)
        context, view_name, subpath, traversed, vroot, vroot_path =(
            tdict['context'], tdict['view_name'], tdict['subpath'],
            tdict['traversed'], tdict['virtual_root'],
            tdict['virtual_root_path'])
        attrs.update(tdict)

        # find a view callable
        context_iface = providedBy(context)
        if routes_multiview is None:
            view = adapters.lookup(
                (IViewClassifier, request_iface, context_iface),
                IView, name=view_name, default=None)
        else:
            view = RoutesMultiView(infos, context_iface, root_factory, request)

        # routes are not registered with a view name
        if view is None:
            view = adapters.lookup(
                (IViewClassifier, request_iface, context_iface),
                IView, name='', default=None)
            # we don't want a multiview here
            if IMultiView.providedBy(view):
                view = None

        if view is not None:
            view.__request_attrs__ = attrs

        return view

    def output_route_attrs(self, attrs, indent):
        route = attrs['matched_route']
        self.out("%sroute name: %s" % (indent, route.name))
        self.out("%sroute pattern: %s" % (indent, route.pattern))
        self.out("%sroute path: %s" % (indent, route.path))
        self.out("%ssubpath: %s" % (indent, '/'.join(attrs['subpath'])))
        predicates = ', '.join([p.__text__ for p in route.predicates])
        if predicates != '':
            self.out("%sroute predicates (%s)" % (indent, predicates))

    def output_view_info(self, view_wrapper, level=1):
        indent = "    " * level
        name = getattr(view_wrapper, '__name__', '')
        module = getattr(view_wrapper, '__module__', '')
        attr = getattr(view_wrapper, '__view_attr__', None)
        request_attrs = getattr(view_wrapper, '__request_attrs__', {})
        if attr is not None:
            view_callable = "%s.%s.%s" % (module, name, attr)
        else:
            attr = view_wrapper.__class__.__name__
            if attr == 'function':
                attr = name
            view_callable = "%s.%s" % (module, attr)
        self.out('')
        if 'matched_route' in request_attrs:
            self.out("%sRoute:" % indent)
            self.out("%s------" % indent)
            self.output_route_attrs(request_attrs, indent)
            permission = getattr(view_wrapper, '__permission__', None)
            if not IMultiView.providedBy(view_wrapper):
                # single view for this route, so repeat call without route data
                del request_attrs['matched_route']
                self.output_view_info(view_wrapper, level+1)
        else:
            self.out("%sView:" % indent)
            self.out("%s-----" % indent)
            self.out("%s%s" % (indent, view_callable))
            permission = getattr(view_wrapper, '__permission__', None)
            if permission is not None:
                self.out("%srequired permission = %s" % (indent, permission))
            predicates = getattr(view_wrapper, '__predicates__', None)
            if predicates is not None:
                predicate_text = ', '.join([p.__text__ for p in predicates])
                self.out("%sview predicates (%s)" % (indent, predicate_text))

    def run(self):
        if len(self.args) < 2:
            self.out('Command requires a config file arg and a url arg')
            return
        config_uri, url = self.args
        if not url.startswith('/'):
            url = '/%s' % url
        env = self.bootstrap[0](config_uri)
        registry = env['registry']
        view = self._find_view(url, registry)
        self.out('')
        self.out("URL = %s" % url)
        self.out('')
        if view is not None:
            self.out("    context: %s" % view.__request_attrs__['context'])
            self.out("    view name: %s" % view.__request_attrs__['view_name'])
        if IMultiView.providedBy(view):
            for dummy, view_wrapper, dummy in view.views:
                self.output_view_info(view_wrapper)
                if IMultiView.providedBy(view_wrapper):
                    for dummy, mv_view_wrapper, dummy in view_wrapper.views:
                        self.output_view_info(mv_view_wrapper, level=2)
        else:
            if view is not None:
                self.output_view_info(view)
            else:
                self.out("    Not found.")
        self.out('')
