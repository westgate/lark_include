import sys
import re
from pathlib import Path

import lark
from lark.lexer import Lexer, LexerState, LexerThread, Token

class BasicError(Exception):
    def __init__(self, *msg):
        self.msg = ' '.join(str(_) for _ in msg)
        super().__init__(self.msg)

# needed a way to store the file name, so added wrapper around LexerState
class RLTLexerState(LexerState):
    def __init__(self, fname, base):
        self.fname = fname
        for value in base.__slots__:
            setattr(self, value, getattr(base, value))

# needed a way to store the file name, so added wrapper around Token
class RLTToken(Token):
    def __new__(cls, base, fname):
        rv = super(RLTToken, cls).__new__(cls, base.type, base.value)
        rv.fname = fname
        for value in base.__slots__:
            setattr(rv, value, getattr(base, value))
        return rv

# this handles the recursion, it looks for a token called "INCLUDE_FILE_NAME"
class RecursiveLexerThread(LexerThread):

    def __init__(self, fname: str, lexer: Lexer, lexer_state):
        self.lexer = lexer

        rltls = RLTLexerState(fname, lexer_state)

        self.state_stack = [rltls]
        self.state = rltls

    @classmethod
    def from_text(cls, fname, lexer: 'Lexer', text: str):
        return cls(fname, lexer, LexerState(text))

    def lex(self, parser_state):
        while self.state_stack:
            self.state = self.state_stack[-1]
            lexer_state = self.state
            lex = self.lexer.lex(lexer_state, parser_state)
            try:
                token = next(lex)
            except StopIteration:
                # We are done with this file
                self.state_stack.pop()
            else:
                if token.type == "INCLUDE_FILE_NAME":
                    fname = token.value
                    try:
                        with open(fname) as data:
                            lexer_state = RLTLexerState(fname, LexerState(data.read()))
                    except FileNotFoundError as err:
                        text = lexer_state.text.split('\n')[token.line-1]
                        raise BasicError(f'{err.strerror} at {lexer_state.fname}:{token.line}:{token.column}: {text}')

                    self.state_stack.append(lexer_state)

                # note: the INCLUDE_FILE_NAME token is returned, but you can ignore it in the AST generation if you wish
                tk = RLTToken(token, lexer_state.fname)
                yield tk

# needed to add filename to lark class
def wrapper_fxn(cls):
    class WrapperCls:
        fname = None
        real_cls = cls

        @classmethod
        def set_fname(cls, fname):
            cls.fname = fname
    
        @classmethod
        def from_text(cls, lexer: 'Lexer', text: str):
            rv = cls.real_cls.from_text(cls.fname, lexer, text)
            return rv

    return WrapperCls

class Parser:

    # generic error method
    @staticmethod
    def _raise(err, msg):
        text = err.state.lexer.state.text.split('\n')[err.line-1]
        fname = err.state.lexer.state.fname
        raise BasicError(f'{msg} at {fname}:{err.line}:{err.column}: {text}')

    # internal method to generate AST
    def _ast(self, text):
        try:
            if self.debug:
                parse = self.parser.parse(text)
                print(parse.pretty())
                print()
                print('DBG: transformer start\n')
                tree = self.transformer.transform(parse)
            else:
                tree = self.parser.parse(text)
        except lark.exceptions.UnexpectedToken as err:
            if err.token.type == '$END':
                self._raise(err, f'Unexpected EOF')
            else:
                self._raise(err, f'Unexpected Token {err.token.value}')
        except lark.exceptions.UnexpectedCharacters as err:
            self._raise(err, 'Unexpected Character {err.token.value}')

        return tree

    # wants a Path object
    def ast_pathlib(self, fh):
        self.cls.set_fname(str(fh))
        tree = self._ast(fh.read_text())
        return tree

    # wants a FH from open
    def ast_open(self, fh):
        self.cls.set_fname(fh.name)
        tree = self._ast(fh.read())
        return tree

    def __init__(self, *, grammar, transformer=None, debug=False):
        cls = wrapper_fxn(RecursiveLexerThread)
        if debug:
            self.parser = lark.Lark(grammar,
                                    debug=True,
                                    start='start',
                                    parser='lalr',
                                    _plugins={"LexerThread": cls},
                                    transformer=None
            )
            self.transformer = transformer
        else:
            self.parser = lark.Lark(grammar,
                                    start='start',
                                    parser='lalr',
                                    _plugins={"LexerThread": cls}, 
                                    transformer=transformer
            )

        self.cls = cls
        self.debug=debug
#**************** end wrapper ****************

def main():

    grammar = r"""
start: ( (include|line)* _EOL)+

include.1 : "include"i INCLUDE_FILE_NAME
INCLUDE_FILE_NAME : /\S+/
     
COMMENT : /#.*/

%ignore COMMENT

_EOL : /\n+/

line     : oses _SEP oses
_SEP      : /(=|-)>/
oses     : os_desc+

os_desc : /[a-z]+/

%ignore /[ \t]+/
"""

    parser = Parser(grammar=grammar)

    tree = parser.ast_pathlib(Path(sys.argv[1]))

    print(tree.pretty())

main()
