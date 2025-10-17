from abc import ABC, abstractmethod

class BaseLogger(ABC):
    @abstractmethod
    def log(self, timestamp, data_list):
        pass

    @abstractmethod
    def create_table_if_not_exists(self):
        pass
