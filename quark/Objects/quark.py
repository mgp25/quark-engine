# This file is part of Quark Engine - https://quark-engine.rtfd.io
# See GPLv3 for copying permission.

import copy
import operator
from quark.utils.out import print_info, print_success
from quark.Evaluator.pyeval import PyEval
from quark.Objects.analysis import QuarkAnalysis
from quark.Objects.apkinfo import Apkinfo
from quark.utils import tools
from quark.utils.colors import (
    red,
    bold,
    yellow,
    green,
)
from quark.utils.graph import call_graph
from quark.utils.output import output_parent_function_table
from quark.utils.weight import Weight

MAX_SEARCH_LAYER = 3
CHECK_LIST = "".join(["\t[" + "\u2713" + "]"])


class Quark:
    """Quark module is used to check quark's five-stage theory"""

    def __init__(self, apk):
        """

        :param apk: the filename of the apk.
        """
        self.apkinfo = Apkinfo(apk)

        self.quark_analysis = QuarkAnalysis()

    def find_previous_method(self, base_method, parent_function, wrapper, visited_methods=None):
        """
        Find the method under the parent function, based on base_method before to parent_function.
        This will append the method into wrapper.

        :param base_method: the base function which needs to be searched.
        :param parent_function: the top-level function which calls the basic function.
        :param wrapper: list is used to track each function.
        :param visited_methods: set with tested method.
        :return: None
        """
        if visited_methods is None:
            visited_methods = set()

        method_set = self.apkinfo.upperfunc(base_method.class_name, base_method.name)
        visited_methods.add(base_method)

        if method_set is not None:

            if parent_function in method_set:
                wrapper.append(base_method)
            else:
                for item in method_set:
                    # prevent to test the tested methods.
                    if item in visited_methods:
                        continue
                    self.find_previous_method(item, parent_function, wrapper, visited_methods)

    def find_intersection(self, first_method_list, second_method_list, depth=1):
        """
        Find the first_method_list ∩ second_method_list.
        [MethodAnalysis, MethodAnalysis,...]

        :param first_method_list: first list that contains each MethodAnalysis.
        :param second_method_list: second list that contains each MethodAnalysis.
        :param depth: maximum number of recursive search functions.
        :return: a set of first_method_list ∩ second_method_list or None.
        """
        # Check both lists are not null
        if first_method_list and second_method_list:

            # find ∩
            result = set(first_method_list).intersection(second_method_list)
            if result:
                return result
            else:
                # Not found same method usage, try to find the next layer.
                depth += 1
                if depth > MAX_SEARCH_LAYER:
                    return None

                # Append first layer into next layer.
                next_list1 = copy.copy(first_method_list)
                next_list2 = copy.copy(second_method_list)

                # Extend the upper function into next layer.
                for method in first_method_list:
                    if self.apkinfo.upperfunc(method.class_name, method.name) is not None:
                        next_list1.extend(
                            self.apkinfo.upperfunc(
                                method.class_name, method.name,
                            ),
                        )
                for method in second_method_list:
                    if self.apkinfo.upperfunc(method.class_name, method.name) is not None:
                        next_list2.extend(
                            self.apkinfo.upperfunc(
                                method.class_name, method.name,
                            ),
                        )

                return self.find_intersection(next_list1, next_list2, depth)
        else:
            raise ValueError("List is Null")

    def check_sequence(self, mutual_parent, first_method_list, second_method_list):
        """
        Check if the first function appeared before the second function.

        :param mutual_parent: function that call the first function and second functions at the same time.
        :param first_method_list: the first show up function, which is (class_name, method_name)
        :param second_method_list: the second show up function, which is (class_name, method_name)
        :return: True or False
        """
        state = False

        for first_call_method in first_method_list:
            for second_call_method in second_method_list:

                seq_table = []

                for _, call, number in mutual_parent.get_xref_to():

                    if call in (first_call_method, second_call_method):
                        seq_table.append((call, number))

                # sorting based on the value of the number
                if len(seq_table) < 2:
                    # Not Found sequence in same_method
                    continue
                seq_table.sort(key=operator.itemgetter(1))
                # seq_table would look like: [(getLocation, 1256), (sendSms, 1566), (sendSms, 2398)]

                method_list_need_check = [x[0] for x in seq_table]
                sequence_pattern_method = [first_call_method, second_call_method]

                if tools.contains(sequence_pattern_method, method_list_need_check):
                    state = True

        return state

    def check_parameter(self, parent_function, first_method_list, second_method_list):
        """
        Check the usage of the same parameter between two method.

        :param parent_function: function that call the first function and second functions at the same time.
        :param first_method_list: function which calls before the second method.
        :param second_method_list: function which calls after the first method.
        :return: True or False
        """
        state = False

        for first_call_method in first_method_list:
            for second_call_method in second_method_list:

                pyeval = PyEval()
                # Check if there is an operation of the same register

                for bytecode_obj in self.apkinfo.get_method_bytecode(
                        parent_function.class_name, parent_function.name,
                ):
                    # ['new-instance', 'v4', Lcom/google/progress/SMSHelper;]
                    instruction = [bytecode_obj.mnemonic]
                    if bytecode_obj.registers is not None:
                        instruction.extend(bytecode_obj.registers)
                    if bytecode_obj.parameter is not None:
                        instruction.append(bytecode_obj.parameter)

                    # for the case of MUTF8String
                    instruction = [str(x) for x in instruction]

                    if instruction[0] in pyeval.eval.keys():
                        pyeval.eval[instruction[0]](instruction)

                for table in pyeval.show_table():
                    for val_obj in table:

                        for c_func in val_obj.called_by_func:

                            first_method_pattern = f"{first_call_method.class_name}->{first_call_method.name}"
                            second_method_pattern = f"{second_call_method.class_name}->{second_call_method.name}"

                            if first_method_pattern in c_func and second_method_pattern in c_func:
                                state = True

                # Build for the call graph
                if state:
                    call_graph_analysis = {"parent": parent_function,
                                           "first_call": first_call_method,
                                           "second_call": second_call_method,
                                           "apkinfo": self.apkinfo,
                                           "first_api": self.quark_analysis.first_api,
                                           "second_api": self.quark_analysis.second_api,
                                           "crime": self.quark_analysis.crime_description,
                                           }
                    self.quark_analysis.call_graph_analysis_list.append(call_graph_analysis)

        return state

    def run(self, rule_obj):
        """
        Run the five levels check to get the y_score.

        :param rule_obj: the instance of the RuleObject.
        :return: None
        """
        self.quark_analysis.clean_result()
        self.quark_analysis.crime_description = rule_obj.crime

        # Level 1: Permission Check
        if set(rule_obj.x1_permission).issubset(set(self.apkinfo.permissions)):
            rule_obj.check_item[0] = True
        else:
            # Exit if the level 1 stage check fails.
            return

        # Level 2: Single Native API Check
        api_1_method_name = rule_obj.x2n3n4_comb[0]["method"]
        api_1_class_name = rule_obj.x2n3n4_comb[0]["class"]
        api_2_method_name = rule_obj.x2n3n4_comb[1]["method"]
        api_2_class_name = rule_obj.x2n3n4_comb[1]["class"]

        first_api = self.apkinfo.find_method(api_1_class_name, api_1_method_name)
        second_api = self.apkinfo.find_method(api_2_class_name, api_2_method_name)

        if first_api is not None or second_api is not None:
            rule_obj.check_item[1] = True

            if first_api is not None:
                first_api = list(self.apkinfo.find_method(api_1_class_name, api_1_method_name))[0]
                self.quark_analysis.level_2_result.append(first_api)
            if second_api is not None:
                second_api = list(self.apkinfo.find_method(api_2_class_name, api_2_method_name))[0]
                self.quark_analysis.level_2_result.append(second_api)
        else:
            # Exit if the level 2 stage check fails.
            return

        # Level 3: Both Native API Check
        if first_api is not None and second_api is not None:
            self.quark_analysis.first_api = first_api
            self.quark_analysis.second_api = second_api
            rule_obj.check_item[2] = True

        else:
            # Exit if the level 3 stage check fails.
            return

        # Level 4: Sequence Check
        # Looking for the first layer of the upper function
        first_api_xref_from = self.apkinfo.upperfunc(first_api.class_name, first_api.name)
        second_api_xref_from = self.apkinfo.upperfunc(second_api.class_name, second_api.name)
        mutual_parent_function_list = self.find_intersection(first_api_xref_from, second_api_xref_from)

        if mutual_parent_function_list is not None:

            for parent_function in mutual_parent_function_list:
                first_wrapper = []
                second_wrapper = []

                self.find_previous_method(first_api, parent_function, first_wrapper)
                self.find_previous_method(second_api, parent_function, second_wrapper)

                if self.check_sequence(parent_function, first_wrapper, second_wrapper):
                    rule_obj.check_item[3] = True
                    self.quark_analysis.level_4_result.append(parent_function)

                    # Level 5: Handling The Same Register Check
                    if self.check_parameter(parent_function, first_wrapper, second_wrapper):
                        rule_obj.check_item[4] = True
                        self.quark_analysis.level_5_result.append(parent_function)

        else:
            # Exit if the level 4 stage check fails.
            return

    def get_json_report(self):
        """
        Get quark report including summary and detail with json format.

        :return: json report
        """

        w = Weight(self.quark_analysis.score_sum, self.quark_analysis.weight_sum)
        warning = w.calculate()

        # Filter out color code in threat level
        for level in ["Low Risk", "Moderate Risk", "High Risk"]:
            if level in warning:
                warning = level

        json_report = {
            "md5": self.apkinfo.md5,
            "apk_filename": self.apkinfo.filename,
            "size_bytes": self.apkinfo.filesize,
            "threat_level": warning,
            "total_score": self.quark_analysis.score_sum,
            "crimes": self.quark_analysis.json_report,
        }

        return json_report

    def generate_json_report(self, rule_obj):
        """
        Show the json report.

        :param rule_obj: the instance of the RuleObject
        :return: None
        """
        # Count the confidence
        confidence = str(rule_obj.check_item.count(True) * 20) + "%"
        conf = rule_obj.check_item.count(True)
        weight = rule_obj.get_score(conf)
        score = rule_obj.yscore

        # Assign level 1 examine result
        permissions = []
        if rule_obj.check_item[0]:
            permissions = rule_obj.x1_permission

        # Assign level 2 examine result
        api = []
        if rule_obj.check_item[1]:
            for class_name, method_name in self.quark_analysis.level_2_result:
                api.append({
                    "class": class_name,
                    "method": method_name,
                })

        # Assign level 3 examine result
        combination = []
        if rule_obj.check_item[2]:
            combination = rule_obj.x2n3n4_comb

        # Assign level 4 - 5 examine result if exist
        sequnce_show_up = []
        same_operation_show_up = []

        # Check examination has passed level 4
        if self.quark_analysis.level_4_result and rule_obj.check_item[3]:
            for same_sequence_cls, same_sequence_md in self.quark_analysis.level_4_result:
                sequnce_show_up.append({
                    "class": repr(same_sequence_cls),
                    "method": repr(same_sequence_md),
                })

            # Check examination has passed level 5
            if self.quark_analysis.level_5_result and rule_obj.check_item[4]:
                for same_operation_cls, same_operation_md in self.quark_analysis.level_5_result:
                    same_operation_show_up.append({
                        "class": repr(same_operation_cls),
                        "method": repr(same_operation_md),
                    })

        crime = {
            "crime": rule_obj.crime,
            "score": score,
            "weight": weight,
            "confidence": confidence,
            "permissions": permissions,
            "native_api": api,
            "combination": combination,
            "sequence": sequnce_show_up,
            "register": same_operation_show_up,
        }
        self.quark_analysis.json_report.append(crime)

        # add the weight
        self.quark_analysis.weight_sum += weight
        # add the score
        self.quark_analysis.score_sum += score

    def show_summary_report(self, rule_obj):
        """
        Show the summary report.

        :param rule_obj: the instance of the RuleObject.
        :return: None
        """
        # Count the confidence
        confidence = str(rule_obj.check_item.count(True) * 20) + "%"
        conf = rule_obj.check_item.count(True)
        weight = rule_obj.get_score(conf)
        score = rule_obj.yscore

        self.quark_analysis.summary_report_table.add_row([
            green(rule_obj.crime), yellow(
                confidence,
            ), score, red(weight),
        ])

        # add the weight
        self.quark_analysis.weight_sum += weight
        # add the score
        self.quark_analysis.score_sum += score

    def show_detail_report(self, rule_obj):
        """
        Show the detail report.

        :param rule_obj: the instance of the RuleObject.
        :return: None
        """

        # Count the confidence
        print("")
        print(f"Confidence: {rule_obj.check_item.count(True) * 20}%")
        print("")

        if rule_obj.check_item[0]:

            print(red(CHECK_LIST), end="")
            print(green(bold("1.Permission Request")), end="")
            print("")

            for permission in rule_obj.x1_permission:
                print(f"\t\t {permission}")
        if rule_obj.check_item[1]:
            print(red(CHECK_LIST), end="")
            print(green(bold("2.Native API Usage")), end="")
            print("")

            for api in self.quark_analysis.level_2_result:
                print(f"\t\t ({api.class_name}, {api.name})")
        if rule_obj.check_item[2]:
            print(red(CHECK_LIST), end="")
            print(green(bold("3.Native API Combination")), end="")

            print("")
            print(
                f"\t\t ({rule_obj.x2n3n4_comb[0]['class']}, {rule_obj.x2n3n4_comb[0]['method']})",
            )
            print(
                f"\t\t ({rule_obj.x2n3n4_comb[1]['class']}, {rule_obj.x2n3n4_comb[1]['method']})",
            )
        if rule_obj.check_item[3]:

            print(red(CHECK_LIST), end="")
            print(green(bold("4.Native API Sequence")), end="")

            print("")
            print(f"\t\t Sequence show up in:")
            for seq_method in self.quark_analysis.level_4_result:
                print(f"\t\t {seq_method.full_name}")
        if rule_obj.check_item[4]:

            print(red(CHECK_LIST), end="")
            print(green(bold("5.Native API Use Same Parameter")), end="")
            print("")
            for seq_operation in self.quark_analysis.level_5_result:
                print(f"\t\t {seq_operation.full_name}")

    def show_call_graph(self):
        print_info("Creating Call Graph...")
        for call_graph_analysis in self.quark_analysis.call_graph_analysis_list:
            call_graph(call_graph_analysis)
        print_success("Call Graph Completed")

    def show_rule_classification(self):
        print_info("Rules Classification")
        output_parent_function_table(self.quark_analysis.call_graph_analysis_list)


if __name__ == "__main__":
    pass
