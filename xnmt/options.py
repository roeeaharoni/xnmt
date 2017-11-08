"""
Stores options and default values
"""
import yaml
import argparse
from collections import OrderedDict
import copy
import random
import inspect
from xnmt.serializer import Serializable

class Option(object):
  def __init__(self, name, opt_type=str, default_value=None, required=None, force_flag=False, help_str=None):
    """
    Defines a configuration option
    :param name: Name of the option
    :param opt_type: Expected type. Should be a base type.
    :param default_value: Default option value. If this is set to anything other than none, and the option is not
    explicitly marked as required, it will be considered optional.
    :param required: Whether the option is required.
    :param force_flag: Force making this argument a flag (starting with '--') even though it is required
    :param help_str: Help string for documentation
    """
    self.name = name
    self.type = opt_type
    self.default_value = default_value
    self.required = required == True or required is None and default_value is None
    self.force_flag = force_flag
    self.help = help_str

class Args(dict):
  pass
          
class RandomParam(yaml.YAMLObject):
  yaml_tag = u'!RandomParam'
  def __init__(self, values):
    self.values = values
  def __repr__(self):
    return "%s(values=%r)" % (
            self.__class__.__name__, self.values)
  def draw_value(self):
    if not hasattr(self, 'drawn_value'):
      self.drawn_value = random.choice(self.values)
    return self.drawn_value

class OptionParser(object):
  def __init__(self):
    self.tasks = {}
    """Options, sorted by task"""

  def add_task(self, task_name, task_options):
    self.tasks[task_name] = {} #OrderedDict([(opt.name, opt) for opt in task_options])

#  def check_and_convert(self, task_name, option_name, value):
#    if option_name not in self.tasks[task_name]:
#      raise RuntimeError("Unknown option {} for task {}".format(option_name, task_name))
#
#    option = self.tasks[task_name][option_name]
#    if not (isinstance(value, RandomParam) or isinstance(value, RefParam) or isinstance(value, Serializable)):
#      value = option.type(value)
#
#    return value

  def args_from_config_file(self, filename):
    """
    Returns a dictionary of experiments => {task => {arguments object}}
    """
    try:
      with open(filename) as stream:
        config = yaml.load(stream)
    except IOError as e:
      raise RuntimeError("Could not read configuration file {}: {}".format(filename, e))

    # Default values as specified in option definitions
#    defaults = {
#      task_name: dict({name: opt.default_value for name, opt in task_options.items() if
#                  opt.default_value is not None or not opt.required})
#      for task_name, task_options in self.tasks.items()}

    experiments  = config
    if "defaults" in experiments: del experiments["defaults"]
    for exp in experiments:
      experiments[exp] = copy.deepcopy(experiments[exp])
      random_search_report = self.instantiate_random_search(experiments[exp])
      if random_search_report:
        experiments[exp]['random_search_report'] = random_search_report
      self.replace_placeholder(experiments[exp], exp)
      for task_name in self.tasks:
        if not task_name in experiments[exp]:
          experiments[exp][task_name] = {}
    

#    experiments = {}
#    for exp, exp_tasks in config.items():
#      if exp=="defaults": continue
#      if exp_tasks is None: exp_tasks = {}
#      experiments[exp] = {}
#      for task_name in self.tasks:
##        task_values = copy.deepcopy(defaults[task_name])
#        task_values = {}
#        exp_task_values = exp_tasks.get(task_name, dict())
#        #task_values.update({name: self.check_and_convert(task_name, name, value) for name, value in exp_task_values.items()})
#        task_values = dict(exp_task_values)
#
#        # Check that no required option is missing
#        for _, option in self.tasks[task_name].items():
#          if option.required:
#            sub_task_values = task_values
#            sub_option_name = option.name
#            if sub_option_name not in sub_task_values:
#              raise RuntimeError(
#                "Required option not found for experiment {}, task {}: {}".format(exp, task_name, option.name))
#
#        # Replace the special token "<EXP>" with the experiment name if necessary
#        for k in task_values.keys():
#          if type(task_values[k]) == str:
#            task_values[k] = task_values[k].replace("<EXP>", exp)
#
#        random_search_report = self.instantiate_random_search(task_values)
#        if random_search_report:
#          task_values["random_search_report"] = random_search_report
#
##        self.resolve_referenced_params(task_values, task_values)
#
#        experiments[exp][task_name] = Args()
#        for name, val in task_values.items():
#          experiments[exp][task_name][name] = val

    return experiments

  def instantiate_random_search(self, exp_values, initialized_random_params={}):
    param_report = {}
    if isinstance(exp_values, dict): kvs = exp_values.items()
    elif isinstance(exp_values, Serializable):
      init_args, _, _, _ = inspect.getargspec(exp_values.__init__)
      kvs = [(key, getattr(exp_values, key)) for key in init_args if hasattr(exp_values, key)]
    for k, v in kvs:
      if isinstance(v, RandomParam):
        if hasattr(v, "_xnmt_id") and v._xnmt_id in initialized_random_params:
          v = initialized_random_params[v._xnmt_id]
        v = v.draw_value()
        if hasattr(v, "_xnmt_id"):
          initialized_random_params[v._xnmt_id] = v
        if isinstance(exp_values, dict):
          exp_values[k] = v
        else:
          setattr(exp_values, k, v)
        param_report[k] = v
      elif isinstance(v, dict) or isinstance(v, Serializable):
        sub_report = self.instantiate_random_search(v, initialized_random_params)
        if sub_report:
          param_report[k] = sub_report
    return param_report

  def replace_placeholder(self, exp_values, value, placeholder="<EXP>"):
    if isinstance(exp_values, dict): kvs = exp_values.items()
    elif isinstance(exp_values, Serializable):
      init_args, _, _, _ = inspect.getargspec(exp_values.__init__)
      kvs = [(key, getattr(exp_values, key)) for key in init_args if hasattr(exp_values, key)]
    for k, v in kvs:
      if isinstance(v, str):
        if placeholder in v:
          if isinstance(exp_values, dict):
            exp_values[k] = v.replace(placeholder, value)
          else:
            setattr(exp_values, k, v.replace(placeholder, value))
      elif isinstance(v, dict) or isinstance(v, Serializable):
        self.replace_placeholder(v, value, placeholder)


#  def resolve_referenced_params(self, cur_task_values, top_task_values):
#    if isinstance(cur_task_values, dict): kvs = cur_task_values.items()
#    elif isinstance(cur_task_values, Serializable):
#      init_args, _, _, _ = inspect.getargspec(cur_task_values.__init__)
#      kvs = [(key, getattr(cur_task_values, key)) for key in init_args if hasattr(cur_task_values, key)]
#    else:
#      raise RuntimeError()
#    for k, v in kvs:
#      if isinstance(v, RefParam):
#        ref_str_spl = v.ref.split(".")
#        resolved = top_task_values
#        for ref_str in ref_str_spl:
#          if isinstance(resolved, dict):
#            resolved = resolved[ref_str]
#          else:
#            resolved = getattr(resolved, ref_str)
#        if isinstance(cur_task_values, dict):
#          cur_task_values[k] = resolved
#        elif isinstance(cur_task_values, Serializable):
#          setattr(cur_task_values, k, resolved)
#      elif isinstance(v, dict) or isinstance(v, Serializable):
#        self.resolve_referenced_params(v, top_task_values)


  def args_from_command_line(self, task, argv):
    parser = argparse.ArgumentParser()
    for option in self.tasks[task].values():
      if option.required and not option.force_flag:
        parser.add_argument(option.name, type=option.type, help=option.help)
      else:
        parser.add_argument("--" + option.name, default=option.default_value, required=option.required,
                            type=option.type, help=option.help)

    return parser.parse_args(argv)

  def remove_option(self, task, option_name):
    if option_name not in self.tasks[task]:
      raise RuntimeError("Tried to remove nonexistent option {} for task {}".format(option_name, task))
    del self.tasks[task][option_name]

  def generate_options_table(self):
    """
    Generates markdown documentation for the options
    """
    lines = []
    for task, task_options in self.tasks.items():
      lines.append("## {}".format(task))
      lines.append("")
      lines.append("| Name | Description | Type | Default value |")
      lines.append("|------|-------------|------|---------------|")
      for option in task_options.values():
        if option.required:
          template = "| **{}** | {} | {} | {} |"
        else:
          template = "| {} | {} | {} | {} |"
        lines.append(template.format(option.name, option.help if option.help else "", option.type.__name__,
                                     option.default_value if option.default_value is not None else ""))
      lines.append("")

    return "\n".join(lines)


# Predefined options for dynet
general_options = [
  Option("dynet_mem", int, required=False),
  Option("dynet_seed", int, required=False),
]
