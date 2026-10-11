"""Shared scalar validation; task-specific constraints stay with the task."""


def validated_options(options, section, *, integers=(), flags=()):
    """Copy options, default positive integer budgets and strict boolean flags."""
    if not isinstance(options, dict):
        raise ValueError(section + '必须是配置对象')
    value = dict(options)
    for key, default, upper in integers:
        number = value.setdefault(key, default)
        # bool is an int subclass, but never a valid resource/time budget.
        if type(number) is not int or not 1 <= number <= upper:
            raise ValueError(f'{section}.{key}必须是1到{upper}的整数')
    for key, default in flags:
        if type(value.setdefault(key, default)) is not bool:
            raise ValueError(f'{section}.{key}必须是布尔值')
    return value
