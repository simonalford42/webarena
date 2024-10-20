from webarena.browser_env import create_id_based_action, create_type_action, create_stop_action, create_none_action, create_type_action, create_keyboard_type_action, Action, ActionTypes

import dateparser
import re

class SecondActionException(Exception):
    pass

class WebThing():
    root = None # effectively a global variable that refers to the current state of the web page

    URL = None # global variable for the current URL

    TOOK_ACTION_ALREADY = False # global variable to help track actions with more than one `click`, `type`, etc.
    RAISE_EXCEPTION_FOR_SECOND_ACTION = False

    # effectively a global variable that refers to the current trajectory. in terms of backend actions, used for evaluation
    low_level_trajectory = []

    # trajectory in terms of high level WebThing actions, used for learning from demonstration
    # each element of the trajectory is a tuple (triple), where:
    # the first element is an URL,
    # second element is WebThing object representing the entire webpage,
    # and the last element is a WebThing API call (what we did at that URL)
    high_level_trajectory = []

    def __init__(self, category: str, name: str, id: int, parent, children, property_names, property_values, original_env=None, nth=0):

        # WARNING: we have custom pickle methods, so if you add new fields, you need to update __getstate__ and __setstate__ as well
        # This is this is super duper important!

        self.name = name
        self.id = id
        self.children = children
        self.parent = parent
        self.category = category
        self.property_names = property_names
        self.property_values = property_values
        self.properties = dict(zip(property_names, property_values))
        self.original_env = original_env
        self.efficient_path = None # signal we havent yet found path to this node
        self.nth = nth

        # parse dates
        if category == "time":
            self.properties["datetime"] = dateparser.parse(self.name)

    def find(self, category=None, name=None, nth=None, match_substrings: bool = False, **kwargs):
        '''
        category and name can be None, a string, or a regex.
        None matches anything.
        '''
        all_results = self.find_all(category, name, nth, match_substrings, **kwargs)
        if all_results:
            return all_results[0]

        # if we didn't find it, try (1) literal match, (2) case insensitive match
        if name:
            # try literal match
            c = None if category is None else re.escape(category)
            n = re.escape(name)
            all_results = self.find_all(c, n, nth, match_substrings, **kwargs)
            if all_results: return all_results[0]

            # try case insensitive match
            c = None if category is None else re.compile(category, re.IGNORECASE)
            n = re.compile(name, re.IGNORECASE)
            all_results = self.find_all(c, n, nth, match_substrings, **kwargs)
            if all_results: return all_results[0]
        return None

    def find_all(self, category=None, name=None, nth=None, match_substrings=False, **kwargs):
        return_value = []
        if self._match(category, name, nth, match_substrings, **kwargs):
            return_value.append(self)
        for child in self.children:
            return_value.extend(child.find_all(category, name, nth, match_substrings, **kwargs))
        return return_value

    def search_forward(self, category=None, name=None, match_substrings=False, **kwargs):
        """looks for a match that occurs after this node (NOT including this node!)"""
        matches = []
        for child in self.children: matches.extend(child.find_all(category, name, match_substrings=match_substrings, **kwargs))

        # now we have to go through our parents and search any of their children that come after us
        parent, latest_child = self.parent, self
        while parent:
            # find the index of this node in the parent's children
            index = parent.children.index(latest_child)
            suffix = parent.children[index+1:]
            for sibling in suffix: matches.extend(sibling.find_all(category, name, match_substrings=match_substrings, **kwargs))

            latest_child = parent
            parent = parent.parent

        return matches

    def search_backward(self, category=None, name=None, match_substrings=False, **kwargs):
        """looks for a match that occurs before this node (NOT including this node!)"""
        matches = []
        parent, latest_child = self.parent, self
        while parent:
            if parent._match(category, name, match_substrings=match_substrings, **kwargs):
                matches.append(parent)

            # find the index of this node in the parent's children
            index = parent.children.index(latest_child)
            prefix = parent.children[:index]
            for sibling in reversed(prefix): matches.extend(sibling.find_all(category, name, match_substrings=match_substrings, **kwargs))

            latest_child = parent
            parent = parent.parent
        return matches

    def get_all_descendants(self):
        """Recursively extracts all children, children of children, etc. of this node"""
        children = [self]
        for child in self.children:
            children += child.get_all_descendants()
        return children

    def click(self):
        self._record_high_level_action("click")
        self._make_in_viewport()
        self._do_action(create_id_based_action(f"click [{self.id}]"))

    def type(self, text):
        '''
        if text is "", clears the text in the textbox
        otherwise, types the text into the textbox
        '''
        self._record_high_level_action("type", text)
        self._make_in_viewport()
        self._do_action(create_type_action(text=text, element_id=str(self.id)))

    def press_enter(self):
        self._record_high_level_action("press_enter")
        self._do_action(create_keyboard_type_action("\n"))

    def go_back(self):
        ''' go back to the previous page'''
        return WebThing.root.original_env.step(create_id_based_action(f"go_back"))

    def let_page_load(self):
        # maybe this should have a way of waiting for longer, or detecting when the page is fully loaded
        self._do_action(create_none_action())

    @staticmethod
    def answer(text):
        WebThing.high_level_trajectory.append((WebThing.URL, WebThing._strip_root(), (None, "print", (f'"{text}"',), {})))
        WebThing.low_level_trajectory.append(create_stop_action(text))

    def reset_trajectory():
        WebThing.low_level_trajectory = list()
        WebThing.high_level_trajectory = list()

    def _match(self, category, name, nth=None, match_substrings=False, **kwargs):
        if match_substrings:
            return (
                (category is None or re.search(category, self.category))
                and (name is None or re.search(name, self.name))
                and (nth is None or self.nth == nth)
                and all(getattr(self, key, None) == value for key, value in kwargs.items())
            )
        else:
            # regexes must match the full string
            return (
                (category is None or re.fullmatch(category, self.category))
                and (name is None or re.fullmatch(name, self.name))
                and (nth is None or self.nth == nth)
                and all(getattr(self, key, None) == value for key, value in kwargs.items())
            )

    def _record_high_level_action(self, method_name, *args, **kwargs):
        WebThing.high_level_trajectory.append((WebThing.URL, WebThing._strip_root(), (self, method_name, args, kwargs)))

    def _do_action(self, action: Action, pause=None):
        """
        helper function that makes sure that states+actions are recorded in the trajectory.
        not used by the agent, which uses higher level functions like `click` and `type` instead.
        """
        if action['action_type'] in [ActionTypes.CLICK, ActionTypes.TYPE, ActionTypes.GO_BACK]:
            if WebThing.TOOK_ACTION_ALREADY and WebThing.RAISE_EXCEPTION_FOR_SECOND_ACTION:
                raise SecondActionException("Attempted a second action in a single code extension")

            WebThing.TOOK_ACTION_ALREADY = True

        WebThing.low_level_trajectory.append(action)
        if pause:
            old_sleep = self.original_env.sleep_after_execution
            self.original_env.sleep_after_execution = pause

        obs, _, _, _, info = self.original_env.step(action)

        if pause:
            self.original_env.sleep_after_execution = old_sleep

        state_info = {"observation": obs, "info": info}
        WebThing.low_level_trajectory.append(state_info)

    def _center(self):
        """normalized coordinates within the viewport of the center of this node"""
        return self.original_env.observation_handler.action_processor.get_element_center(str(self.id))

    def _make_in_viewport(self):
        target_height = 0.3
        old_ys = []
        # disabled blurring because it seems to mess up clicking menuitems from drop down menus
        # we might just have to settle for centering not working sometimes?
        first_time = True
        while True:
            center = self._center()
            y = center[1]
            if y in old_ys: # can't scroll anymore, looping
                break
            old_ys.append(y)
            if y < 0:
                self._do_action(create_id_based_action(f"scroll [up]"), pause=0.2)
            elif y > 1:
                self._do_action(create_id_based_action(f"scroll [down]"), pause=0.2)
            elif 0 <= y <= target_height:
                if first_time:
                    # if some element besides self is focused, blur it
                    for element in WebThing.root.get_all_descendants():
                        if element.properties.get("focused", True) and element != self:
                            WebThing._blur()
                            break

                    first_time = False
                self._do_action(create_id_based_action(f"press [arrowup]"), pause=0.2)
            elif 0.5+target_height <= y <= 1:
                if first_time:
                    # if some element besides self is focused, blur it
                    for element in WebThing.root.get_all_descendants():
                        if element.properties.get("focused", True) and element != self:
                            WebThing._blur()
                            break

                    first_time = False
                self._do_action(create_id_based_action(f"press [arrowdown]"), pause=0.2)
            else:
                break

    def __repr__(self):
        representation = f"{self.category}('{self.name}'"
        if self.properties:
            for property_name in self.property_names:
                representation += f", {property_name}={self.properties[property_name]}"
        if self.children:
            representation += f", children={repr(self.children)}"
        representation += ")"
        return representation

    def __str__(self):
        return repr(self)

    def markdown(self, listdepth=0):

        def join(things):
            """joins together things with spaces if they don't have otherwise separating whitespace"""
            the_join = ""
            for thing in things:
                if the_join and thing and not thing[0].isspace() and not the_join[-1].isspace():
                    the_join += " "
                the_join += thing
            while "\n\n\n" in the_join:
                the_join = the_join.replace("\n\n\n", "\n\n")
            return the_join

        if self.category == "main":
            child_markdown = join(child.markdown() for child in self.children)
            return f"\n\n# {self.category} {self.name}\n\n{child_markdown}\n\n"

        if self.category == "complementary":
            child_markdown = join(child.markdown() for child in self.children)
            if self.name == "":
                return f"# {self.category}\n{child_markdown}"
            return f"\n\n# {self.name}\n\n{child_markdown}\n\n"

        if self.category == "navigation":
            child_markdown = join(child.markdown() for child in self.children)
            return f"\n\n## {self.category} {self.name}\n{child_markdown}\n\n"

        if self.category == "heading":
            if len(self.children) == 0:
                return f"\n## {self.name}\n"
            else:
                return join([f"[heading: {self.name}]"]+[child.markdown() for child in self.children])

        if self.category=='table':
            return join([f"[table: {self.name}]\n"] + [child.markdown()+"\n" for child in self.children])
        if self.category == "row":
            if any(child.category == "columnheader" for child in self.children):
                assert all(child.category == "columnheader" for child in self.children)
                return "| " + " | ".join(child.markdown() for child in self.children) + " |\n| " + " | ".join(":---:" for _ in self.children) + " |"
            if any(child.category == "gridcell" for child in self.children):
                assert all(child.category == "gridcell" for child in self.children)
                return "| " + " | ".join(child.markdown() for child in self.children) + " |"
            assert 0, f"unexpected children for {self.category} {self.name}"
        if self.category in ["columnheader", "gridcell"]:
            assert len(self.children) <= 1
            if len(self.children) == 0:
                return self.name
            else:
                return self.children[0].markdown()

        if self.category == "link":
            if "hover_text" in self.properties:
                return f"[link: {self.name} {self.hover_text}]"
            return f"[link: {self.name}]"

        if self.category in ["button", "time", "searchbox", "textbox"]:
            if len(self.children) == 0:
                return f"[{self.category}: {self.name}]"
            if len(self.children) == 1 and self.children[0].category.lower() == "statictext":
                return f"[{self.category}: {self.name}],  {self.children[0].name}"
            assert 0, f"unexpected children for {self.category} {self.name}"

        if self.category == "switch":
            return f"[switch, checked={int(self.checked)}: {self.name}]"

        if self.category == "RootWebArea":
            everything = "\n".join(child.markdown() for child in self.children)
            while "\n\n\n" in everything:
                everything = everything.replace("\n\n\n", "\n\n")
            return everything

        if self.category == "list":
            list_marker = ["*", "-", "+"][listdepth % 3]
            # check that all of the children are listitems
            assert all(child.category == "listitem" for child in self.children), f"unexpected type of children for list {self.name}/{self.nth}"
            children = [child.markdown(listdepth+1) for child in self.children]
            # every single child has now been processed into a string
            # the first line of each child should have "*\t" prepended
            # the rest of the lines should have "\t" prepended

            marked_children = []
            for child in children:
                lines = child.split("\n")
                for line_number, line in enumerate(lines):
                    if line_number == 0:
                        marked_children.append(f"{list_marker}\t{line}")
                    else:
                        marked_children.append(f"\t{line}")
            return "\n" + "\n".join(marked_children) + "\n"

        if self.category == "listitem":
            return join(child.markdown() for child in self.children)

        if self.category.lower() == "statictext":
            return self.name

        if self.category.lower() == "image":
            return f"[image: {self.name}]"

        if self.category.lower() == "generic":
            return join([self.name]+[child.markdown() for child in self.children])

        if self.category.lower() == "group":
            if self.name == "":
                return join(child.markdown() for child in self.children)
            else:
                return join([f"[group: {self.name}]"]+[child.markdown() for child in self.children])

        return f"UNDEFINED({self.category} {self.name})"

    # make it so that you can do like `thing.a_property`
    def __getattr__(self, name):
        if name in self.properties:
            return self.properties[name]
        if "datetime" in self.properties:
            try: return getattr(self.properties["datetime"], name)
            except: pass
        raise AttributeError(f"'{self.category}' object has no attribute '{name}'")

    # __getattr__ interferes with pickle
    # so we have to define custom __getstate__ and __setstate__ to handle the properties
    # WARNING: if you add new fields, you need to update __getstate__ and __setstate__ as well
    def __getstate__(self):
        return (self.category, self.name, self.id, self.parent, self.children, self.property_names, self.property_values, self.properties, self.nth)

    def __setstate__(self, state):
        self.category, self.name, self.id, self.parent, self.children, self.property_names, self.property_values, self.properties, self.nth = state
        self.original_env = None
        self.efficient_path = None

    def serialize(self, indent=0):
        serialization = f"{'    '*indent}[{self.id}] {self.category} '{self.name}'"
        if self.properties:
            try:
                serialization += " " + " ".join(f"{key}={self.properties[key]}" for key in self.property_names)
            except KeyError as e:
                print(self.property_names)
                print(self.properties.keys())
                import pdb; pdb.set_trace()

        serialization += "\n"
        for child in self.children:
            serialization += child.serialize(indent+1)
        return serialization

    def pretty(self, indent=0):
        """pretty print it in a way that the llm (hopefully) understands"""
        serialization = f"{'    '*indent}category='{self.category}', name='{self.name}', nth={self.nth}"
        if self.properties:
            serialization += ", " + ", ".join(f"{key}={repr(self.properties[key])}" for key in self.properties)

        serialization += "\n"
        for child in self.children:
            serialization += child.pretty(indent+1)
        return serialization

    def pretty_path(self, is_target=True):
        representation = f"{self.category}({repr(self.name)}, nth={self.nth}"
        if self.properties:
            for property_name in self.property_names:
                representation += f", {property_name}={self.properties[property_name]}"
        representation += ")"

        if is_target:
            if self.parent:
                return representation + f", nth={self.nth}, which is under " + self.parent.pretty_path(is_target=False)
            else:
                return representation
        else:
            if self.parent:
                if "list" in self.category and self.name == "":
                    return self.parent.pretty_path(is_target=False)
                return self.parent.pretty_path(is_target=False) + " / " + representation
            else:
                return representation

    def clean(self):
        # analogous to clean_accessibility_tree, but with extra cleaning heuristics
        # 1. removes statictext children that are substrings of the parent's name (clean_accessibility_tree also does this)
        # 2. remove image children with either empty names or same name as parent (they are meaningless because we are text only)
        # 3. remove empty links (how could we ever refer to them or click on them?)
        # 4. remove hidden say anything with hidden=True
        # 5. merge adjacent statictext children if they are childless and have no properties
        # 6. remove hover_text if it is identical to the name when stripped of whitespace and punctuation, and made lowercase
        # 7. merge category='time', with singleton StaticText child, make the child a field called "relative"
        # 8. Remove children of buttons
        # 9. Remove "status" if it has no name or children
        # Last (optional): remove "article", "SvgRoot" and "contentinfo" elements, they are usually just bunch of boring words and links
        new_children = []
        for child in self.children:
            if child.category.lower() == "statictext":
                if child.name in self.name:
                    continue
            if child.category.lower() == "image" and len(child.children) == 0:
                if child.name.strip().replace(":", "").replace("_", " ") in ["", self.name]:
                    continue
            if child.category == "link" and child.name.strip() == "":
                continue
            if child.properties.get("hidden", False):
                continue
            if self.category.lower() == "time" and child.category.lower() == "statictext" and len(child.children) == 0 and len(child.property_names) == 0 and len(self.children) == 1:
                self.property_names.append("relative")
                self.property_values.append(child.name)
                self.properties["relative"] = child.name
                continue
            if child.category.lower() in ["article", "contentinfo", "svgroot"] and len(child.children) == 0:
                continue
            if self.category == "button":
                continue
            if child.category == "status" and child.name.strip() == "" and len(child.children) == 0:
                continue
            new_children.append(child.clean())
        # merge adjacent statictext children if they are childless and have no properties
        new_new_children = []
        for child in new_children:
            if child.category.lower() == "statictext" and len(new_new_children) > 0 and new_new_children[-1].category.lower() == "statictext" \
                and len(child.children) == 0 and len(new_new_children[-1].children) == 0 and len(child.property_names) == 0 and len(new_new_children[-1].property_names) == 0:
                new_new_children[-1].name += " " + child.name
            else:
                new_new_children.append(child)
        self.children = new_new_children
        if "hover_text" in self.properties:
            self.properties["hover_text"] = self.hover_text.strip().replace("\n", " ")
            if self.hover_text.strip().replace(" ", "").replace("_", "").lower() == self.name.strip().replace(" ", "").replace("_", "").lower():
                self.properties.pop("hover_text")
        # remove focus property from RootWebArea
        if "RootWebArea" == self.category:
            if "focused" in self.properties:
                self.properties.pop("focused")
        return self

    # def hover(self):
        # self._record_high_level_action("hover")
        # action = create_hover_action(element_role=self.category, element_name=self.name, nth=self.nth)
        # self._do_action(action)
        # self._make_in_viewport()
        # self._do_action(create_id_based_action(f"hover [{self.id}]"))

    def _blur():
        """ remove keyboard focus from currently focused element """
        # per Claude AI recommendation
        WebThing.root.original_env.page.locator('body').evaluate(
            "() => document.activeElement && document.activeElement.blur()")

    def assign_nths(root):
        nodes = root.get_all_descendants()
        # map (category, name) to how many times we've seen it
        nth_dict = {}
        for node in nodes:
            key = (node.category, node.name)
            if key not in nth_dict:
                nth_dict[key] = 0
            else:
                nth_dict[key] += 1
            node.nth = nth_dict[key]

    # Removes all non-pickle-able things from the root, particularly which refer to the environment
    # Returns a new root, but without updating the root pointer
    @staticmethod
    def _strip_root():
        return WebThing.root._strip(memo=None)

    # Removes all non-pickle-able things from the tree, particularly which refer to the environment
    # Has the invariant that the parent has always already been added to the memo table
    def _strip(self, memo=None):

        if memo is None:
            memo = dict()

        if id(self) in memo:
            return memo[id(self)]

        new_parent = memo[id(self.parent)] if self.parent else None
        new_children = list() # cannot recurs on the children without breaking the invariant
        new_thing = WebThing(self.category, self.name, self.id, new_parent, new_children,
                             self.property_names, self.property_values, original_env=None, nth=self.nth)

        memo[id(self)] = new_thing

        # now we can do the children
        for child in self.children:
            new_thing.children.append(child._strip(memo))

        return new_thing
