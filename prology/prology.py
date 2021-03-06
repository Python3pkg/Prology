from collections import *
from inspect import signature
from operator import indexOf
from contextlib import contextmanager
from abc import ABCMeta, abstractmethod

__all__ = ["unify", "Predicate", "PredicateProxy", "Instance", "Variable", "PyPred", "Equal", "IsFrom", "Not", "L", "cons", "peach", "plist", "switch", "nil", "true", "false"]


def instantiate(f):
    return f()


def unify(this, that, env=None):
    if env is None:
        env = {}
    if isinstance(this, Instance):
        env = {**this._vars, **env}
    if isinstance(that, Instance):
        env = {**that._vars, **env}
    links = defaultdict(set)

    def bind(var, val):
        toBind = set()
        toBind.add(var)
        while toBind:
            rem = toBind.pop()
            toBind |= links.get(rem, set())
            if links.get(rem, _notfound) is not _notfound:
                del links[rem]

            if env[rem] is not rem:
                push(env[rem], val)
            else:
                env[rem] = val

    def push(this, that):
        states.append((this, that))

    def link(this, that):
        links[this].add(that)
        links[that].add(this)

    states = [(this, that)]
    while states:
        (this, that) = states.pop()
        # if this == that: TODO: uncomment?
        #    continue

        # Are those two instances?
        if isinstance(this, Instance) and isinstance(that, Instance):
            if this.predicate != that.predicate or len(this._args) != len(that._args):
                return None
            for a, b in zip(this._args, that._args):
                push(a, b)
            continue

        # if this is not a variable
        if not isinstance(this, Variable):
            if not isinstance(that, Variable):
                # both not variables => must be equal
                if this != that:
                    return None
                continue
            else:  # that is a variable, not this
                bind(that, this)
            continue
        # so this is a variable. if that is not a variable
        if not isinstance(that, Variable):
            bind(this, that)
            continue

        # Now, both are Variables
        if env[this] == this:
            if env[that] == that:
                link(this, that)
            else:
                bind(this, env[that])
        elif env[that] == that:
            bind(that, env[this])
        else:
            # both have values
            push(env[this], env[that])

    # Now, we close the linking by clustering equal variables
    while links:
        rem = next(iter(links))
        toLink = links[rem]
        del links[rem]
        while toLink:
            linked = toLink.pop()
            if linked != rem:
                env[linked] = rem

            toLink |= links[linked]
            if links.get(linked, _notfound) is not _notfound:
                del links[linked]
    return env


_notfound = object()

class Variable:

    def __init__(self, name, number=0):
        self.name = name
        self.number = number
        self.hash = hash((self.name, self.number))

    def __hash__(self):
        return self.hash

    def __eq__(self, other):
        if not isinstance(other, Variable):
            return False
        return self.name == other.name and self.number == other.number

    def eval(self, subst):
        val = subst.get(self, self)
        if val is not self and isinstance(val, Variable):
            return val.eval(subst)
        if isinstance(val, Instance):
            return val.eval(subst)
        return val

    def __repr__(self):
        if self.number is 0:
            return self.name
        return "{}#{}".format(self.name, self.number)


def rebind(predicate, i, takenVariables):
    subst = {}
    for v in predicate._vars[i]:
        number = takenVariables[v] = takenVariables[v] + 1
        new = Variable(v.name, number)
        subst[v] = new
    return predicate.facts[i].eval(subst), [body.eval(subst) for body in predicate.bodies[i]]


class Instance(metaclass=ABCMeta):

    @property
    @abstractmethod
    def predicate(self):
        pass

    @property
    @abstractmethod
    def _vars(self):
        """Yields an iterable of unbound variables used in the instance"""
        pass

    @property
    @abstractmethod
    def _args(self):
        """The tuple of arguments"""
        pass

    @abstractmethod
    def eval(self, subst):
        """Apply create a new instance by substituting unbound variables"""
        pass

    @abstractmethod
    def ask(self, takenVars=None):
        """Yields substitutions making the instance true."""
        pass

    @abstractmethod
    def eval(self, subst):
        pass

    def ever(self):
        return next(self.ask(), None) is not None

    def never(self):
        return next(self.ask(), None) is None

    def fill(self):
        subst = next(self.ask(), None)
        if subst is None:
            return None
        return self.eval(subst)

    @property
    def first(self):
        subst = next(self.ask(), None)
        return subst

    def all(self, var=None):
        ret = list(self.ask())
        if var:
            return [r[var] for r in ret]
        return ret

    def __getitem__(self, key):
        try:
            if isinstance(key, str):
                return self._args[self.predicate.keys[key]]
            return self._args[key]
        except (KeyError, IndexError):
            raise KeyError("Predicate {} has no item {}".format(self.predicate.name, key))

    def __getattr__(self, key):
        try:
            return self._args[self.predicate.keys[key]]
        except KeyError:
            raise AttributeError("Predicate {} has no attribute {}".format(self.predicate.name, key))

    def __bool__(self):
        return self.ever()

class PyInstance(Instance):
    predicate = None
    _vars = None
    _args = None

    def __init__(self, predicate, args):
        self.predicate = predicate
        self._args = args

        self._vars = {}
        for arg in args:
            if isinstance(arg, Variable):
                self._vars[arg] = arg
            elif isinstance(arg, Instance):
                self._vars.update(arg._vars)

    def __repr__(self):
        if not self._args:
            return str(self.predicate)
        return "{}({})".format(self.predicate, ", ".join(repr(arg) for arg in self._args))

    def __eq__(self, other):
        if not isinstance(other, Instance):
            return False
        return self.predicate == other.predicate and self._args == other._args

    def eval(self, subst):
        newargs = [0]*len(self._args)
        for i, arg in enumerate(self._args):
            if isinstance(arg, (Variable, Instance)):
                newargs[i] = arg.eval(subst)
            else:
                newargs[i] = arg

        return PyInstance(self.predicate, tuple(newargs))

    def known(self):
        return self.known_when()

    def known_when(self, *args):
        self.predicate._vars.append(set(self._vars) | set(var for arg in args for var in arg._vars))
        self.predicate.facts.append(self)
        self.predicate.bodies.append(args)
        return self.predicate

    def ask(self, takenVars=None):
        """Yields a possible substitution, toRename contains the variable names
        already taken (since fsubst and subst coexist)"""
        if takenVars is None:
            takenVars = defaultdict(int)
        for i in range(len(self.predicate.facts)):
            fact, body = rebind(self.predicate, i, takenVars)  # gets the fact and rebinds it
            fsubst = unify(self, fact)  # try unifying with the fact
            if fsubst is None:
                continue

            if not body:  # if no body, just yield the substitution
                yield {k: v.eval(fsubst) for k, v in self._vars.items()}
                continue

            stack = [(0, fsubst, None)]  # Otherwise, perform a DFS on the possible unifications with body
            while stack:
                j, fsubst, gen = stack.pop()
                if gen is None:
                    gen = body[j].eval(fsubst).ask(takenVars)
                subst = next(gen, None)
                if subst is None:
                    continue
                stack.append((j, fsubst, gen))

                fsubst = {**fsubst, **subst}  # unbounded overrided
                if j == len(body)-1:  # yield if at the end of the body
                    yield {k: v.eval(fsubst) for k, v in self._vars.items()}
                else:
                    stack.append((j+1, fsubst, None))  # if not at the end, go one step further


class PythonPredicate:

    def __init__(self, fct, vars=None):
        self.fct = fct
        if vars is None:
            params = signature(fct).parameters
            self._vars = [Variable(name) for name in params]
        else:
            self._vars = vars

    def eval(self, subst):
        return PythonPredicate(self.fct, [v.eval(subst) if isinstance(v, (Variable, Instance)) else v for v in self._vars])

    def ask(self, takenVars=None):
        for answer in self.fct(*self._vars):
            yield answer


def PyPred(fct):
    if isinstance(fct, Instance):  # Use as decorator - register
        instance = fct
        def _(fct):
            instance.known_when(PythonPredicate(fct))
            return fct
        return _
    else:
        return PythonPredicate(fct)  # Use as wrapper for function


class Predicate:

    def __init__(self, name, keys=None):
        self.name = name
        self._vars = []
        self.facts = []
        self.bodies = []
        self.keys = {k: i for i, k in enumerate(keys.split(" ")) if k != ""} if keys is not None else None

    def __getitem__(self, params):
        inst = self(*params) if isinstance(params, tuple) else self(params)
        inst.known()

    def __setitem__(self, params, conditions):
        inst = self(*params) if isinstance(params, tuple) else self(params)
        if isinstance(conditions, tuple):
            inst.known_when(*conditions)
        else:
            inst.known_when(conditions)

    def __call__(self, *args):
        return PyInstance(self, args)

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return self is other


class PredicateProxy:
    def __init__(self, f):
        self.f = f

    def __call__(self, *args, **kwargs):
        return self.f(*args, **kwargs)

    def __getitem__(self, params):
        inst = self.f(*params) if isinstance(params, tuple) else self.f(params)
        inst.known()

    def __setitem__(self, params, conditions):
        inst = self.f(*params) if isinstance(params, tuple) else self.f(params)
        if isinstance(conditions, tuple):
            inst.known_when(*conditions)
        else:
            inst.known_when(conditions)


@instantiate
class L:
    """Syntactic sugar for creating variables: _.V and prology lists: _[_.A, _.B]"""
    def __getattr__(self, name):
        return Variable(name)

    def __getitem__(self, iterable):
        if isinstance(iterable, tuple):
            return plist(*iterable)
        else:
            return cons(iterable, nil)

_ = L


def plist(*iterable):
    """Creates a prology list from arguments"""
    current = nil
    for item in iterable[::-1]:
        current = cons(item, current)
    return current


def peach(plist, fct):
    """Applies fct on a prology list and returns the result in a python list
    """
    ret = []
    while plist != nil:
        ret.append(fct(plist._args[0]))
        plist = plist._args[1]
    return ret


Equal = Predicate("equal")
Equal(_.A, _.A).known()


Not = Predicate("not")
@PyPred(Not(_.A))
def _not(A):
    if isinstance(A, Instance):
        if A.never():
            yield {}
        return
    raise Exception("'Not' only works with predicate instances. Got {}.".format(A))


IsFrom = Predicate("isfrom")
@PyPred(IsFrom(_.A, _.T))
def _isinstance(A, T):
    if isinstance(A, Instance) and A.predicate == T:
        yield {}


class _Presentator:
    def __init__(self, tomatch, subst):
        self.tomatch = tomatch
        self.subst = subst

    def __iter__(self):
        if self.subst is not None:
            yield self.tomatch

    def __ror__(self, left):
        if self.subst is None:
            return
        if isinstance(left, tuple):
            yield tuple(self.subst[e] for e in left)
        elif isinstance(left, list):
            yield list(self.subst[e] for e in left)
        else:
            yield self.subst[left]


def switch(tomatch):
    skip = False
    def _(pattern):
        nonlocal skip
        if skip:
            return _Presentator(tomatch, None)
        subst = unify(pattern, tomatch)
        if subst is not None:
            skip = True
        return _Presentator(tomatch, subst)
    def default():
        nonlocal skip
        if not skip:
            skip = True
            yield tomatch
    def reset():
        nonlocal skip
        skip = False
        _.default = default()
    _.default = default()
    _.reset = reset
    return _


cons = Predicate("cons", "a b")
cons(_.A, _.B).known()
nil = Predicate("nil")()
true = Predicate("true")()
true.known()
false = Predicate("false")()
