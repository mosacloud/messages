// This will be replaced at build time with the value of 
// the SCRIPT_GROUP_ATTRIBUTE_WHITELIST environment variable
var attributesWhitelist = SCRIPT_GROUP_ATTRIBUTE_WHITELIST;

var groups = user.getGroupsStream().toArray();

for (var i = 0; i < groups.length; i++) {
  var group = groups[i];
  if (!group) continue;

  for (var j = 0; j < attributesWhitelist.length; j++) {
    var attributeName = attributesWhitelist[j];
    var value = group.getFirstAttribute(attributeName);
    if (value !== null && value !== undefined && value !== "") {
      token.getOtherClaims().put(attributeName, value);
      break;
    }
  }
}