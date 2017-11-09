#!/usr/bin/env python3

"""
Reads experiments descriptions in the passed configuration file
and runs them sequentially, logging outputs to files called <experimentname>.log
and <experimentname>.err.log, and reporting on final perplexity metrics.
"""

import argparse
import sys
import os
import six
import random
import shutil
import numpy as np
import copy

# XNMT imports
import xnmt.xnmt_preproc, xnmt.train, xnmt.xnmt_decode, xnmt.xnmt_evaluate
from xnmt.options import OptionParser
from xnmt.tee import Tee
from xnmt.serializer import YamlSerializer, UninitializedYamlObject
from xnmt.model_context import ModelContext, PersistentParamCollection

def main(overwrite_args=None):
  argparser = argparse.ArgumentParser()
  argparser.add_argument("--dynet-mem", type=int)
  argparser.add_argument("--dynet-seed", type=int)
  argparser.add_argument("--dynet-autobatch", type=int)
  argparser.add_argument("--dynet-devices", type=str)
  argparser.add_argument("--dynet-viz", action='store_true', help="use visualization")
  argparser.add_argument("--dynet-gpu", action='store_true', help="use GPU acceleration")
  argparser.add_argument("--dynet-gpu-ids", type=int)
  argparser.add_argument("--dynet-gpus", type=int)
  argparser.add_argument("--dynet-weight-decay", type=float)
  argparser.add_argument("--generate-doc", action='store_true', help="Do not run, output documentation instead")
  argparser.add_argument("experiments_file")
  argparser.add_argument("experiment_name", nargs='*', help="Run only the specified experiments")
  argparser.set_defaults(generate_doc=False)
  args = argparser.parse_args(overwrite_args)

  config_parser = OptionParser()

  # Tweak the options to make config files less repetitive:
  # - Delete evaluate:evaluator, replace with exp:eval_metrics
  # - Delete decode:hyp_file, evaluate:hyp_file, replace with exp:hyp_file
  # - Delete train:model, decode:model_file, replace with exp:model_file

#  experiment_options = [
#    Option("model_file", default_value="<EXP>.mod", help_str="Location to write the model file"),
#    Option("hyp_file", default_value="<EXP>.hyp", help_str="Location to write decoded output for evaluation"),
#    Option("out_file", default_value="<EXP>.out", help_str="Location to write stdout messages"),
#    Option("err_file", default_value="<EXP>.err", help_str="Location to write stderr messages"),
#    Option("cfg_file", default_value=None, help_str="Location to write a copy of the YAML configuration file", required=False),
#    Option("eval_only", bool, default_value=False, help_str="Skip training and evaluate only"),
#    Option("eval_metrics", default_value="bleu", help_str="Comma-separated list of evaluation metrics (bleu/wer/cer)"),
#    Option("run_for_epochs", int, help_str="How many epochs to run each test for"),
#  ]

  if args.generate_doc:
    print(config_parser.generate_options_table())
    exit(0)

  if args.dynet_seed:
    random.seed(args.dynet_seed)
    np.random.seed(args.dynet_seed)

  config = config_parser.args_from_config_file(args.experiments_file)

  results = []

  # Check ahead of time that all experiments exist, to avoid bad surprises
  experiment_names = args.experiment_name or config.keys()

  if args.experiment_name:
    nonexistent = set(experiment_names).difference(config.keys())
    if len(nonexistent) != 0:
      raise Exception("Experiments {} do not exist".format(",".join(list(nonexistent))))

  for experiment_name in sorted(experiment_names):
    exp_tasks = config[experiment_name]

    print("=> Running {}".format(experiment_name))
    
    exp_args = exp_tasks.get("experiment", {})
    # TODO: hack, refactor
    if not "model_file" in exp_args: exp_args["model_file"] = "<EXP>.mod"
    if not "hyp_file" in exp_args: exp_args["hyp_file"] = "<EXP>.hyp"
    if not "out_file" in exp_args: exp_args["out_file"] = "<EXP>.out"
    if not "err_file" in exp_args: exp_args["model_file"] = "<EXP>.err"
    if not "cfg_file" in exp_args: exp_args["cfg_file"] = None
    if not "eval_only" in exp_args: exp_args["eval_only"] = False
    if not "eval_metrics" in exp_args: exp_args["eval_metrics"] = "bleu"
    if "cfg_file" in exp_args and exp_args["cfg_file"] != None:
      shutil.copyfile(args["experiments_file"], exp_args["cfg_file"])

    preproc_args = exp_tasks.get("preproc", {})

    train_args = exp_tasks["train"]
    train_args.model_file = exp_args["model_file"] # TODO: can we use param sharing for this?
    model_context = ModelContext()
    model_context.dynet_param_collection = PersistentParamCollection(exp_args["model_file"], 1)
    train_args = YamlSerializer().initialize_if_needed(UninitializedYamlObject(train_args), model_context)
    
    # TODO: hack, need to refactor
#    if "batcher" in train_args and train_args["batcher"] is not None: train_args["batcher"] = UninitializedYamlObject(train_args["batcher"])
#    if "trainer" in train_args and train_args["trainer"] is not None: train_args["trainer"] = UninitializedYamlObject(train_args["trainer"])
#    if "training_corpus" in train_args and train_args["training_corpus"] is not None: train_args["training_corpus"] = UninitializedYamlObject(train_args["training_corpus"])
#    if "corpus_parser" in train_args and train_args["corpus_parser"] is not None: train_args["corpus_parser"] = UninitializedYamlObject(train_args["corpus_parser"])
#    if "model" in train_args and train_args["model"] is not None: train_args["model"] = UninitializedYamlObject(train_args["model"])
#    if "training_strategy" in train_args and train_args["training_strategy"] is not None: train_args["training_strategy"] = UninitializedYamlObject(train_args["training_strategy"])

    decode_args = exp_tasks.get("decode", {})
    decode_args["trg_file"] = exp_args["hyp_file"]
    decode_args["model_file"] = None  # The model is passed to the decoder directly

    evaluate_args = exp_tasks.get("evaluate", {})
    evaluate_args["hyp_file"] = exp_args["hyp_file"]
    evaluators = map(lambda s: s.lower(), exp_args["eval_metrics"].split(","))

    output = Tee(exp_args["out_file"], 3)
    err_output = Tee(exp_args["err_file"], 3, error=True)

    # Do preprocessing
    print("> Preprocessing")
    xnmt.xnmt_preproc.xnmt_preproc(**preproc_args)

    # Do training
    if "random_search_report" in exp_tasks:
      print("> instantiated random parameter search: %s" % exp_tasks["random_search_report"])

    print("> Training")
    xnmt_trainer = train_args
    xnmt_trainer.decode_args = copy.copy(decode_args)
    xnmt_trainer.evaluate_args = copy.copy(evaluate_args)

    eval_scores = "Not evaluated"
    if not exp_args["eval_only"]:
      xnmt_trainer.run_epochs(exp_args["run_for_epochs"])

    if not exp_args["eval_only"]:
      print('reverting learned weights to best checkpoint..')
      xnmt_trainer.model_context.dynet_param_collection.revert_to_best_model()
    if evaluators:
      print("> Evaluating test set")
      output.indent += 2
      xnmt.xnmt_decode.xnmt_decode(model_elements=(
        xnmt_trainer.corpus_parser, xnmt_trainer.model), **decode_args)
      eval_scores = []
      for evaluator in evaluators:
        evaluate_args["evaluator"] = evaluator
        eval_score = xnmt.xnmt_evaluate.xnmt_evaluate(**evaluate_args)
        print(eval_score)
        eval_scores.append(eval_score)
      output.indent -= 2

    results.append((experiment_name, eval_scores))

    output.close()
    err_output.close()

  print("")
  print("{:<30}|{:<40}".format("Experiment", " Final Scores"))
  print("-" * (70 + 1))

  for line in results:
    experiment_name, eval_scores = line
    for i in range(len(eval_scores)):
      print("{:<30}| {:<40}".format((experiment_name if i==0 else ""), str(eval_scores[i])))

if __name__ == '__main__':
  import _dynet
  dyparams = _dynet.DynetParams()
  dyparams.from_args()
  sys.exit(main())
