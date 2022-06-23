class NetError(Exception):
    def __str__(self):
        return "发生网络异常!!!"