from flet import (
    Page,
    NavigationRail,
    NavigationRailDestination,
    NavigationRailLabelType,
    ControlEvent,
    Column,
    icons,
    colors,
)

class Sidebar(Column):

    def __init__(self, page:Page):
        super().__init__()
        self.page = page
        self.nav = NavigationRail(
            selected_index=0,
            bgcolor=colors.GREY_200,
            label_type=NavigationRailLabelType.SELECTED,
            on_change=self.on_nav_change,
            expand=True,
            destinations=[
                NavigationRailDestination(
                    icon=icons.HOME_OUTLINED,
                    selected_icon=icons.HOME,
                    label="Home",
                ),
                NavigationRailDestination(
                    icon=icons.SCHEDULE_OUTLINED,
                    selected_icon=icons.SCHEDULE,
                    label="Schedule",
                )
            ]
        )
    

    def build(self):
        self.controls = [
            self.nav
        ]
    

    def on_nav_change(self, e:ControlEvent):
        index = e if type(e) == int else e.control.selected_index
        self.nav.selected_index = index
        if index == 0:
            self.page.go("/home")
        elif index == 1:
            self.page.go("/schedule")