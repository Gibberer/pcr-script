from flet import (
    Page,
    TemplateRoute,
    Row,
    Text,
    Container,
    Theme
)
from gui.pages.sidebar import Sidebar
from gui.pages.home import HomeView
from gui.storage import KVStorage
from gui.pages.schedule import ScheduleView

class App(Row):
    def __init__(self, page: Page) -> None:
        super().__init__()
        self.page = page
        self.page.fonts = {"SHS": "https://www.unpkg.com/font-online/fonts/SourceHanSans/SourceHanSans-Normal.otf"}
        self.page.theme = Theme(font_family="SHS")
        KVStorage.init(page.client_storage)
        self.expand = True
        self.current_view = None
        self.spacing = 0
        self.sidebar = Sidebar(page)
        self.page.on_route_change = self.on_route_change
        self._home = None
        self._schedule = None

    @property
    def home(self):
        if not self._home:
            self._home = HomeView()
        return self._home
    
    @property
    def schedule(self):
        if not self._schedule:
            self._schedule = ScheduleView()
        return self._schedule
    
    def setup_views(self):
        self.controls = [
            self.sidebar,
            Container(
              content=self.current_view,
              expand=True 
            ),
        ]

    def on_route_change(self, e):
        troute = TemplateRoute(self.page.route)
        if troute.match("/"):
            self.page.go("/home")
        elif troute.match("/home"):
            self.current_view = self.home
        elif troute.match("/schedule"):
            self.current_view = self.schedule
        self.setup_views()
        self.page.update()
