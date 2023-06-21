import urllib.request
from ordered_set import OrderedSet
from typing import Dict, List, Union, Set, Callable
import time, requests, re, uuid, base64, hmac, functools, json

from .exceptions import InvalidSourceOrTargetLanguage, TranslatorSetupFailure, MissingTranslatorParams, TranslatorNotValid
from ..textdetector.textblock import TextBlock
from ..base import BaseModule
from utils.registry import Registry
from utils.io_utils import text_is_empty
from .hooks import chs2cht

TRANSLATORS = Registry('translators')
register_translator = TRANSLATORS.register_module

PROXY = urllib.request.getproxies()

LANGMAP_GLOBAL = {
    'Auto': '',
    '简体中文': '',
    '繁體中文': '',
    '日本語': '',
    'English': '',
    '한국어': '',
    'Tiếng Việt': '',
    'čeština': '',
    'Nederlands': '',
    'français': '',
    'Deutsch': '',
    'magyar nyelv': '',
    'italiano': '',
    'polski': '',
    'português': '',
    'limba română': '',
    'русский язык': '',
    'español': '',
    'Türk dili': ''        
}

SYSTEM_LANG = ''
SYSTEM_LANGMAP = {
    'zh-CN': '简体中文'        
}


def check_language_support(check_type: str = 'source'):
    
    def decorator(set_lang_method):
        @functools.wraps(set_lang_method)
        def wrapper(self, lang: str = ''):
            if check_type == 'source':
                supported_lang_list = self.supported_src_list
            else:
                supported_lang_list = self.supported_tgt_list
            if not lang in supported_lang_list:
                msg = '\n'.join(supported_lang_list)
                raise InvalidSourceOrTargetLanguage(f'Invalid {check_type}: {lang}\n', message=msg)
            return set_lang_method(self, lang)
        return wrapper

    return decorator


class BaseTranslator(BaseModule):

    concate_text = True
    cht_require_convert = False
    
    def __init__(self,
                 lang_source: str, 
                 lang_target: str,
                 raise_unsupported_lang: bool = True,
                 **params) -> None:
        super().__init__(**params)
        self.name = ''
        for key in TRANSLATORS.module_dict:
            if TRANSLATORS.module_dict[key] == self.__class__:
                self.name = key
                break
        self.textblk_break = '\n###\n'
        self.lang_source: str = lang_source
        self.lang_target: str = lang_target
        self.lang_map: Dict = LANGMAP_GLOBAL.copy()
        self.postprocess_hooks = OrderedSet()
        
        try:
            self.setup_translator()
        except Exception as e:
            if isinstance(e, MissingTranslatorParams):
                raise e
            else:
                raise TranslatorSetupFailure(e)

        self.valid_lang_list = [lang for lang in self.lang_map if self.lang_map[lang] != '']

        try:
            self.set_source(lang_source)
            self.set_target(lang_target)
        except InvalidSourceOrTargetLanguage as e:
            if raise_unsupported_lang:
                raise e
            else:
                lang_source = self.supported_src_list[0]
                lang_target = self.supported_tgt_list[0]
                self.set_source(lang_source)
                self.set_target(lang_target)

        if self.cht_require_convert:
            self.register_postprocess_hooks(self._chs2cht)

    def register_postprocess_hooks(self, callbacks: Union[List, Callable]):
        if callbacks is None:
            return
        if isinstance(callbacks, Callable):
            callbacks = [callbacks]
        for callback in callbacks:
            self.postprocess_hooks.add(callback)

    def _setup_translator(self):
        raise NotImplementedError

    def setup_translator(self):
        self._setup_translator()

    @check_language_support(check_type='source')
    def set_source(self, lang: str):
        self.lang_source = lang

    @check_language_support(check_type='target')
    def set_target(self, lang: str):
        self.lang_target = lang

    def _translate(self, text: Union[str, List]) -> Union[str, List]:
        raise NotImplementedError

    def translate(self, text: Union[str, List]) -> Union[str, List]:
        if text_is_empty(text):
            return text

        concate_text = isinstance(text, List) and self.concate_text
        text_source = self.textlist2text(text) if concate_text else text
        
        text_trans = self._translate(text_source)
        
        if text_trans is None:
            if isinstance(text, List):
                text_trans = [''] * len(text)
            else:
                text_trans = ''
        elif concate_text:
            text_trans = self.text2textlist(text_trans)
            
        if isinstance(text, List):
            assert len(text_trans) == len(text)
            for ii, t in enumerate(text_trans):
                for callback in self.postprocess_hooks:
                    text_trans[ii] = callback(t)
        else:
            for callback in self.postprocess_hooks:
                text_trans = callback(text_trans)

        return text_trans

    def textlist2text(self, text_list: List[str]) -> str:
        # some translators automatically strip '\n'
        # so we insert '\n###\n' between concated text instead of '\n' to avoid mismatch
        return self.textblk_break.join(text_list)

    def text2textlist(self, text: str) -> List[str]:
        breaker = self.textblk_break.replace('\n', '') or '\n'
        text_list = text.split(breaker)
        return [text.lstrip().rstrip() for text in text_list]

    def translate_textblk_lst(self, textblk_lst: List[TextBlock]):
        text_list = [blk.get_text() for blk in textblk_lst]
        translations = self.translate(text_list)
        for tr, blk in zip(translations, textblk_lst):
            for callback in self.postprocess_hooks:
                tr = callback(tr, blk=blk)
            blk.translation = tr

    def supported_languages(self) -> List[str]:
        return self.valid_lang_list

    @property
    def supported_tgt_list(self) -> List[str]:
        return self.valid_lang_list

    @property
    def supported_src_list(self) -> List[str]:
        return self.valid_lang_list
    
    def _chs2cht(self, text: str, blk: TextBlock = None):
        if self.lang_target == '繁體中文':
            return chs2cht(text)
        else:
            return text
        
    def delay(self) -> float:
        if 'delay' in self.params:
            delay = self.params['delay']
            if delay:
                try:
                    return float(delay)
                except:
                    pass
        return 0.