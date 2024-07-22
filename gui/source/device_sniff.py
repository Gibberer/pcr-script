from pcrscript.driver import Driver
from .models import Device,SourceType


class _SimulatorDuck:

    def get_devices(self) -> list[str]:
        pass
    def get_dirvers(self) -> list[Driver]:
        pass


class SniffSource:

    def devices(self)->list[Device]:
        pass

class SniffSourceWrapper(SniffSource):
    
    def __init__(self, simulator:_SimulatorDuck, source:SourceType) -> None:
        super().__init__()
        self.simulator = simulator
        self.source_type = source
    
    def devices(self) -> list[Device]:
        devices = self.simulator.get_devices()
        drivers = self.simulator.get_dirvers()
        if not devices or not drivers:
            return []
        assert len(devices) == len(drivers)
        return [Device(name=name,driver=driver,device_type=self.source_type) for name, driver in zip(devices, drivers)]


class DeviceSniff:
    
    def __init__(self, sources:list[SourceType]=None) -> None:
        self.update_source(sources)
    
    def update_source(self, sources:list[SourceType]):
        if not sources:
            sources = [SourceType.General]
        sources = set(sources)
        self.sources:list[SniffSource] = []
        for source in sources:
            if source == SourceType.General:
                from pcrscript.simulator import GeneralSimulator
                self.sources.append(SniffSourceWrapper(GeneralSimulator(),source))
            elif source == SourceType.Leidian:
                from pcrscript.simulator import DNSimulator
                self.sources.append(SniffSourceWrapper(DNSimulator(path="",fastclick=True, useADB=False), source))
            elif source == SourceType.MuMu12:
                from pcrscript.simulator import MuMuSimulator
                self.sources.append(SniffSourceWrapper(MuMuSimulator(path=""), source))
    
    def find_devices(self) -> list[Device]:
        result = []
        for source in self.sources:
            result += source.devices()
        return result