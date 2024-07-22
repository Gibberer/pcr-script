import flet as ft
from gui.app import App

def main(page: ft.Page):
    page.title = "公主连结脚本控制台"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.padding = 0
    app = App(page)
    page.add(app)
    page.go(page.route)


ft.app(main)