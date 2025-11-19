class AutoAllocationApiLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    rule_id = models.IntegerField()
    operation = models.CharField(max_length=20)  # 'create', 'update', 'delete', 'deactivate'
    condition_count = models.IntegerField(default=0)
    action_count = models.IntegerField(default=0)
    triggered_by = models.CharField(max_length=100)
    message = models.TextField()

def post(self, request):
    data = request.data
    try:
        rule_data = data.get('rulemaster', {})
        condition_list = data.get('condition', [])
        action_list = data.get('action', [])

        rulemaster = AutoAllocationRuleMaster.objects.create(**rule_data)

        for condition_data in condition_list:
            AutoAllocationRuleCondition.objects.create(rule_id=rulemaster, **condition_data)

        for action_data in action_list:
            AutoAllocationRuleAction.objects.create(rule_id=rulemaster, **action_data)

        message = f"Created rulemaster {rulemaster.rule_id} ('{rulemaster.rule_name}') successfully."

        AutoAllocationApiLog.objects.create(
            rule_id=rulemaster.rule_id,
            operation='create',
            condition_count=len(condition_list),
            action_count=len(action_list),
            triggered_by=str(request.user),
            message=message
        )

        return Response({"message": message}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def patch(self, request):
    data = request.data
    try:
        rule_data = data.get('rulemaster', {})
        condition_list = data.get('condition', [])
        action_list = data.get('action', [])

        rulemaster = AutoAllocationRuleMaster.objects.get(rule_id=rule_data.get('rule_id'))

        for field, value in rule_data.items():
            if hasattr(rulemaster, field):
                setattr(rulemaster, field, value)
        rulemaster.save()

        updated_conditions = []
        for condition_data in condition_list:
            condition_id = condition_data.get('condition_id')
            if condition_id:
                condition = AutoAllocationRuleCondition.objects.get(id=condition_id, rule_id=rulemaster)
                for field, value in condition_data.items():
                    if field != "condition_id" and hasattr(condition, field):
                        setattr(condition, field, value)
                condition.save()
                updated_conditions.append(condition)

        updated_actions = []
        for action_data in action_list:
            action_id = action_data.get('action_id')
            if action_id:
                action = AutoAllocationRuleAction.objects.get(id=action_id, rule_id=rulemaster)
                for field, value in action_data.items():
                    if field != "action_id" and hasattr(action, field):
                        setattr(action, field, value)
                action.save()
                updated_actions.append(action)

        message = f"Updated rulemaster {rulemaster.rule_id} ('{rulemaster.rule_name}')"
        if updated_conditions:
            message += f", conditions: {', '.join(f'{c.id} ({c.parameter})' for c in updated_conditions)}"
        if updated_actions:
            message += f", actions: {', '.join(f'{a.id} ({a.action_param})' for a in updated_actions)}"
        message += " successfully."

        AutoAllocationApiLog.objects.create(
            rule_id=rulemaster.rule_id,
            operation='update',
            condition_count=len(updated_conditions),
            action_count=len(updated_actions),
            triggered_by=str(request.user),
            message=message
        )

        return Response({"message": message}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def delete(self, request):
    data = request.data
    try:
        rule_id = data.get('rule_id')
        condition_ids = data.get('condition_id')  # expects list
        action_ids = data.get('action_id')        # expects list

        if not rule_id:
            return Response({"error": "Missing rule_id"}, status=status.HTTP_400_BAD_REQUEST)

        rulemaster = AutoAllocationRuleMaster.objects.get(rule_id=rule_id)

        deleted_conditions = []
        deleted_actions = []

        if condition_ids:
            conditions = AutoAllocationRuleCondition.objects.filter(id__in=condition_ids, rule_id=rule_id)
            deleted_conditions = list(conditions)
            conditions.delete()

        if action_ids:
            actions = AutoAllocationRuleAction.objects.filter(id__in=action_ids, rule_id=rule_id)
            deleted_actions = list(actions)
            actions.delete()

        if not condition_ids and not action_ids:
            rulemaster.is_active = False
            rulemaster.save()
            message = f"rulemaster {rule_id} deactivated"
            operation = "deactivate"
        else:
            message = f"Deleted from rulemaster {rule_id}"
            if deleted_conditions:
                message += f", conditions: {', '.join(f'{c.id} ({c.parameter})' for c in deleted_conditions)}"
            if deleted_actions:
                message += f", actions: {', '.join(f'{a.id} ({a.action_param})' for a in deleted_actions)}"
            message += " successfully."
            operation = "delete"

        AutoAllocationApiLog.objects.create(
            rule_id=rulemaster.rule_id,
            operation=operation,
            condition_count=len(deleted_conditions),
            action_count=len(deleted_actions),
            triggered_by=str(request.user),
            message=message
        )

        return Response({"message": message}, status=status.HTTP_200_OK)

    except AutoAllocationRuleMaster.DoesNotExist:
        return Response({"error": "Rulemaster not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#procode 
# 
def evaluate_rule(rulemaster, input_data):
    """
    Evaluates a rulemaster against input_data.
    input_data: dict like {'departure_time': '08:00', 'destination': 'DEL'}
    Returns: list of triggered actions
    """
    conditions = rulemaster.conditions.all()
    actions = rulemaster.actions.all()

    group_results = {}  # group_id → bool

    for condition in conditions:
        param = condition.parameter
        operator = condition.operator
        value = condition.value
        input_value = input_data.get(param)

        result = False
        if operator == '=':
            result = str(input_value) == str(value)
        elif operator == 'in':
            result = str(input_value) in value.split(',')
        elif operator == 'between':
            start, end = value.split('-')
            result = start <= str(input_value) <= end

        # Group-wise logical aggregation
        group_id = condition.group_id
        if group_id not in group_results:
            group_results[group_id] = result
        else:
            if condition.logical_operator == 'AND':
                group_results[group_id] = group_results[group_id] and result
            elif condition.logical_operator == 'OR':
                group_results[group_id] = group_results[group_id] or result

    # Final rule decision: all groups must be True
    if all(group_results.values()):
        return [
            {
                "action_param": action.action_param,
                "value": action.value
            }
            for action in actions
        ]
    return []                