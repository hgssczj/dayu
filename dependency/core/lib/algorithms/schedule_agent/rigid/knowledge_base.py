from .integrated_safe_predictor import IntegratedSafePredictor
import copy
import math
import threading
import time

# 包含知识库，并提供分类器的使用


class KnowledgeBase():


    def __init__(self,
                 kb_path, 
                 service_name_pipeline, 
                 corrector_param,
                 queue_param,
                 knob_value_range_dict, 
                 delay_cons,
                 raw_meta_data, 
                 stop_threshold
                 ):
        
        self.cur_task_id = -1

        self.performance_predictor=IntegratedSafePredictor(kb_path=kb_path,
                                                       service_name_pipeline=service_name_pipeline,
                                                       corrector_param=corrector_param,
                                                       queue_param=queue_param)
        self.knob_value_range_dict = copy.deepcopy(knob_value_range_dict)
        self.optional_knob_name_list = ['fps','resolution', 'buffer_size', 'edge_serv_num']
        '''
        knob_value_range_dict={
                                        'fps':[1,2,3,4,5,10,15,25,30],
                                        'resolution':['240p','360p','480p','540p','720p','900p','1080p'],
                                        'buffer_size':[10,9,8,7,6,5,4,3,2],
                                        'edge_serv_num':[0,2]
                                    }
        '''
        
        self.delay_cons = delay_cons

        self.raw_meta_data = copy.deepcopy(raw_meta_data)

        self.stop_threshold = stop_threshold


    # 外部调度器通过这个接口来更新性能预估器本身
    def update_corrector(self, context_info, conf_info, task_info):

        #传入一个最新的task_id
        self.cur_task_id = task_info['task_id']

        self.performance_predictor.update_corrector(context_info=context_info,
                                                    conf_info=conf_info,
                                                    task_info=task_info)

    # 基于选定的chosen_knob_list, 来获取最小化时延和最大化精度的权重，以供负反馈使用
    # 这些权重实际上是最小化时延和最大化精度的方向，最后都归一化
    def get_delay_decrease_and_acc_increase_weight(self, cur_policy, cur_context, chosen_knob_list):

        delay_decrease_weight = {}
        acc_increase_weight = {}
        cur_delay, cur_acc = self.pre_delay_and_acc(context_info = cur_context,
                                                    conf_info = cur_policy)

        for knob in list(cur_policy.keys()):
            
            if knob not in chosen_knob_list:

                delay_decrease_weight[knob] = 0
                acc_increase_weight[knob] = 0
            
            else:
   
                delay_if_add, acc_if_add, new_policy = self.get_delay_and_acc_if_knob_change_dir_units(policy = cur_policy,
                                                                                                    context = cur_context,
                                                                                                    knob = knob,
                                                                                                    dir = 1)
                delay_if_dec, acc_if_dec, new_policy = self.get_delay_and_acc_if_knob_change_dir_units(policy = cur_policy,
                                                                                                    context = cur_context,
                                                                                                    knob = knob,
                                                                                                    dir = -1)
                weight = 0

                if delay_if_add < delay_if_dec:  
                    weight = max(0, cur_delay - delay_if_add) / cur_delay

                elif delay_if_dec < delay_if_add: 
                    weight = 0 - max(0, cur_delay - delay_if_dec) / cur_delay

                else:
                    weight = 0
                
                delay_decrease_weight[knob] = weight

    
                if acc_if_add > acc_if_dec:  
                   weight = max(0, acc_if_add - cur_acc) / acc_if_add
                
                elif acc_if_dec > acc_if_add: 
                    weight = 0 - max(0, acc_if_dec - cur_acc) / acc_if_dec

                else:
                    weight = 0

                acc_increase_weight[knob] = weight
        
        # 对于delay_decrease_weight, acc_increase_weight，要归一化为长度为1的向量
        # 这样做可以防止向量太长或者太短。
        norm_delay_decrease_weight = self.normalize_vector(dictionary = delay_decrease_weight)
        norm_acc_increase_weight = self.normalize_vector(dictionary = acc_increase_weight)


        return norm_delay_decrease_weight, norm_acc_increase_weight

    # 以下函数能够将一个字典对应的向量进行等比例缩放，使之长度为1
    def normalize_vector(self, dictionary):
        # 提取字典中的所有值
        values = list(dictionary.values())
        # 计算向量的长度（欧几里得范数）
        vector_length = math.sqrt(sum(x**2 for x in values))
        # 避免除以零的情况（如果所有值都是0）
        if vector_length == 0: #此时不需要归一化，返回原始结果
            return dictionary
        # 否则，对每个值进行等比例缩放
        normalized_values = [x / vector_length for x in values]
        # 返回新的字典，键保持不变，值为缩放后的值
        return {key: value for key, value in zip(dictionary.keys(), normalized_values)}

    # 评估配置和运行时情境下的时延和精度
    def pre_delay_and_acc(self, context_info, conf_info):
        
        delay = self.performance_predictor.delay_pre(context_info = context_info,
                                                     conf_info=conf_info,
                                                     latest_task_id = self.cur_task_id+1,
                                                     if_correct = True)
        acc = self.performance_predictor.acc_pre(context_info = context_info,
                                                 conf_info = conf_info,
                                                 if_correct=True)
        
        # 基于fps校正delay

        delay *= ( conf_info['fps'] / self.raw_meta_data['fps'])

        
        return delay, acc

    # 评估某配置旋钮变化后的性能:dir为1就增加knob 1个单位，dir为-1就减小knob 1个单位，dir为0就一动不动。总之就是获取指定knob移动dir个单位后的新时延和精度
    def get_delay_and_acc_if_knob_change_dir_units(self, policy, context, knob, dir):
        cur_knob_value = policy[knob]
        cur_knob_idx = self.knob_value_range_dict[knob].index(cur_knob_value)
        # print()
        # print('当前要修改的配置',knob,cur_knob_value)
        new_knob_idx = min(len(self.knob_value_range_dict[knob])-1, max(0,cur_knob_idx + dir))
        # print('初始索引和修改方向',cur_knob_idx , dir)
        # print('新索引',new_knob_idx)
        new_policy = copy.deepcopy(policy)
        new_policy[knob] = self.knob_value_range_dict[knob][new_knob_idx]
        # print('初始配置',policy)
        # print('修改配置',new_policy)
        # print()
        new_delay,new_acc = self.pre_delay_and_acc(context_info=context, conf_info=new_policy)

        return new_delay,new_acc, new_policy

    
    # 基于时延和精度计算损失
    def cal_score(self, delay ,acc):
        score = 0
        if delay >= self.delay_cons:
            score = 1 - ( (delay - self.delay_cons) / delay )
        else:
            score = 1+acc
        
        return score
    
    # 贪心搜索，被用于求新的收敛点。新的收敛点可以用于结合当前配置计算待修改的配置旋钮
    def greedy_search(self, policy, cur_context, score, all_knob_list):
        # print('开始搜索')

        # pathw为搜索路径，需要记录整个搜索路径上全部的配置和相应的loss
        path_policy = copy.deepcopy(policy)
        path_score = score

        path_record = []
        path_record.append(
            {
                'policy':path_policy,
                'score':path_score
            }
        )


        # 选出一个knob后就不再考虑剩下的knob，有点像深度优先搜索
        left_knob_list = copy.deepcopy(all_knob_list)

        # 开始进行优先队列搜索，依次尝试不同的配置旋钮来进行搜索。每次都基于path_policy开始搜索。
        for i in range(0, len(left_knob_list)):
            
            # 首先选出当前配置下最值得的修改的knob以及相应的方向，注意best_dir可能为0
            best_knob, best_dir, best_score = self.choose_knob_by_score(cur_policy = path_policy,
                                                    cur_context = cur_context,
                                                    cur_score = path_score,
                                                    knob_list = left_knob_list)
   
            
            # 如果为0，说明搜索可以终止了
            if best_dir == 0:
                break

            # 如果为1或者-1，就沿着这个knob和相应的方向一路搜索下去
            elif best_dir in [1,-1]:

                tmp_policy, tmp_score = self.get_best_policy_score_in_one_dir(cur_policy = path_policy,
                                                                              cur_score = path_score,
                                                                              cur_context = cur_context,
                                                                              knob = best_knob,
                                                                              dir = best_dir)
                path_record.append(
                    {
                        'policy':tmp_policy,
                        'score':tmp_score
                    }
                )
                
                # 如果loss已经小于0.05且十分有限，就停止继续搜索
                if path_score > 1 and tmp_score > 1:
                    if 0 <= (tmp_score - path_score) <= self.stop_threshold*path_score:
                        # print('已经收敛,当前score',tmp_score,'此前score',path_score, '阈值',self.stop_threshold*path_score)
                        break
                
                # 如果无法终止搜索，那就继续前行
                path_policy = tmp_policy
                path_score = tmp_score
                left_knob_list.remove(best_knob)
            
            else:
                assert('wrong dir in choose_knobs_by_search')
        return path_record


    # 在搜索过程中，选择能够让loss最小的配置
    def choose_knob_by_score(self, cur_policy, cur_context, cur_score, knob_list):

        best_knob = ''
        best_dir = 0
        best_score = cur_score
        # print('初始score',best_score)

        for knob in knob_list:
            for dir in [-1,1]:

                new_delay, new_acc, new_policy = self.get_delay_and_acc_if_knob_change_dir_units(policy = cur_policy,
                                                                            context = cur_context,
                                                                            knob = knob,
                                                                            dir = dir
                                                                            )
                new_score = self.cal_score(delay = new_delay,
                                           acc = new_acc)
                
                # print('新时延精度和分数',new_delay, new_acc,new_score)
                
                if new_score > best_score:
                    best_score = new_score
                    best_knob = knob
                    best_dir = dir

        return best_knob, best_dir, best_score


    # 在搜索过程中，基于一个配置旋钮以及方向，沿着这个方向寻找能够使得loss最小的配置，并返回最终的loss和配置
    def get_best_policy_score_in_one_dir(self, cur_policy, cur_score, cur_context, knob, dir):

        if dir not in [1,-1]:
            assert('Wrong dir in change_knob_in_one_dir')

        best_policy = copy.deepcopy(cur_policy)
        best_score = cur_score

        dir_num = 0
        while True:
            dir_num += 1

            new_delay,new_acc, new_policy = self.get_delay_and_acc_if_knob_change_dir_units(policy = best_policy,
                                                                                            context = cur_context,
                                                                                            knob = knob,
                                                                                            dir = dir_num*dir)
            new_score = self.cal_score(delay = new_delay, acc = new_acc)

            if new_score > best_score:

                best_score = new_score
                best_policy = new_policy
            
            else:
                # 如果继续增长不能使得score更大，立刻停止
                break
        
        return best_policy, best_score





        
        

        
    

