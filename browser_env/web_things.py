class WebThing():
    #(role, name, int(obs_node_id), parent, children, property_names, property_values, env)
    def __init__(self, category: str, name: str, id: int, parent, children, property_names, property_values, original_env=None):
        self.name = name
        self.id = id
        self.children = children
        self.parent = parent
        self.category = category
        self.property_names = property_names
        self.property_values = property_values
        self.properties = dict(zip(property_names, property_values))
        self.original_env = original_env

    def __repr__(self):
        representation = f"{self.category}('{self.name}', {self.id}"
        if self.properties:
            for property_name in self.property_names:
                representation += f", {property_name}={self.properties[property_name]}"
        if self.children:
            representation += f", children={repr(self.children)}"
        representation += ")"
        return representation

    def repr_no_children(self):
        representation = f"{self.category}('{self.name}', {self.id}"
        if self.properties:
            for property_name in self.property_names:
                representation += f", {property_name}={self.properties[property_name]}"
        representation += ")"
        return representation

    def __str__(self):
        return repr(self)    

    # make it so that you can do like `thing.a_property`
    def __getattr__(self, name):
        if name in self.properties:
            return self.properties[name]
        raise AttributeError(f"'{self.category}' object has no attribute '{name}'")

    def serialize(self, indent=0):
        serialization = f"{'    '*indent}[{self.id}] {self.category} '{self.name}'"
        if self.properties:
            serialization += " " + " ".join(f"{key}={self.properties[key]}" for key in self.property_names)
        serialization += "\n"
        for child in self.children:
            serialization += child.serialize(indent+1)
        return serialization

    def find_thing_by_id(self, id):
        if self.id == id:
            return self
        for child in self.children:
            result = child.find_thing_by_id(id)
            if result:
                return result
        return None

    def get_path(self):
        if self.parent:
            return self.parent.get_path() + " / " + self.repr_no_children()
        return self.repr_no_children()

    def clean(self):
        # analogous to clean_accessibility_tree
        # removes statictext children that are substrings of the parent's name
        new_children = []
        for child in self.children:
            if child.category.lower() == "statictext":
                if child.name in self.name:
                    continue
            new_children.append(child.clean())
        self.children = new_children
        return self