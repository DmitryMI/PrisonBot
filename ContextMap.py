import logging
from discord.ext import commands

class ContextMap(dict):

    def convert_key(self, context):
        conv = None
        if context.guild:
            conv = context.guild.id
        else:
            conv = context.author.id
        logging.info(f"Context converted to {conv}")
        return conv

    def __setitem__(self, key, item):
        key_conv = self.convert_key(key)
        self.__dict__[key_conv] = item

    def __getitem__(self, key):
        key_conv = self.convert_key(key)
        return self.__dict__[key_conv]

    def __repr__(self):
        return repr(self.__dict__)

    def __len__(self):
        return len(self.__dict__)

    def __delitem__(self, key):
        key_conv = self.convert_key(key)
        del self.__dict__[key_conv]

    def clear(self):
        return self.__dict__.clear()

    def copy(self):
        return self.__dict__.copy()

    def has_key(self, k):
        key_conv = self.convert_key(k)
        return key_conv in self.__dict__

    def update(self, *args, **kwargs):
        return self.__dict__.update(*args, **kwargs)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def pop(self, *args):
        return self.__dict__.pop(*args)

    def __cmp__(self, dict_):
        return self.__cmp__(self.__dict__, dict_)

    def __contains__(self, item):
        if isinstance(item, commands.Context):
            item = self.convert_key(item)

        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __unicode__(self):
        return unicode(repr(self.__dict__))





