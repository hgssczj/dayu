
import json
import copy

# 用于实现流形
class DictStrSet:

    def __init__(self):
        # 存储字典对象列表
        self.dict_obj_list = []
    
    # 返回深度拷贝的列表
    def get_values_copy(self):
        return copy.deepcopy(self.dict_obj_list)

    # 获取列表长度，也就是元素数量
    def get_length(self):
        return len(self.dict_obj_list)
    
    # 添加新的字典对象
    def add_dict_obj(self, dict_obj):

        self.dict_obj_list.append(dict_obj)
    
    # 对元素进行去重处理
    def remove_duplication(self):

        str_set = set()
        for dict_obj in self.dict_obj_list:
            tmp_str = DictStrSet.trans_dict_to_str(dict_obj=dict_obj)
            str_set.add(tmp_str)
        
        # 然后清空原始列表
        self.dict_obj_list.clear()
        # 然后重新填充列表
        for tmp_str in str_set:
            dict_obj = DictStrSet.trans_str_to_dict(tmp_str=tmp_str)
            self.dict_obj_list.append(dict_obj)

    # 按照某个键的取值进行排序，可以选择升序或者降序。一般是降序，比如if_dec=True就表示降序
    def sort_by_key(self, key:str, if_dec:bool):
        
        # 如果reverse为True，那么就可以降序排序
        # 否则，就是升序排序
        self.dict_obj_list.sort(key=lambda x:x[key], reverse=if_dec)
    
    # 获取列表中第一个元素的值的某个键的值
    def get_first_dict_obj_key(self, key):
        res = None
        if len(self.dict_obj_list) > 0:
            res = self.dict_obj_list[0][key]

        return res
    
    # 获取第一个元素的值，但是不删除
    def get_first_dict_obj(self):
        res = None
        if len(self.dict_obj_list) > 0:
            res = self.dict_obj_list[0]

        return res

    # 删除第一个元素的值
    def delete_first_dict_obj(self):
        res = None
        if len(self.dict_obj_list) > 0:
            res = self.dict_obj_list[0]
            del self.dict_obj_list[0]

        return res
    
    
    # 清空整个列表
    def delete_all(self):
        # 删除列表里的全部元素
        self.dict_obj_list.clear()
    # 保留前num个值
    def save_first_num_dict_obj(self, num):
        assert num > 0

        # 如下，只保留前num个
        self.dict_obj_list[:] = self.dict_obj_list[:num]

    @staticmethod #转化字典为字符串
    def trans_dict_to_str(dict_obj):
        # sort_keys=True确保了转化为字符串前会将字典中的键排序，确保只要键值对内容相同就可以得到相同字符串
        # 否则，内容相同的字典会因为键的顺序不同出现不一样的字符串
        return json.dumps(dict_obj, sort_keys=True)

    @staticmethod #转化字符串为字典
    def trans_str_to_dict(tmp_str):
        return json.loads(tmp_str)


    

