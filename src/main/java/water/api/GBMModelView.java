package water.api;

import hex.gbm.GBM.GBMModel;
import water.*;
import water.api.RequestBuilders.Response;

public class GBMModelView extends Request2 {
  static final int API_WEAVER = 1; // This file has auto-gen'd doc & json fields
  static public DocGen.FieldDoc[] DOC_FIELDS; // Initialized from Auto-Gen code.

  @API(help="GBM Model Key", required=true, filter=GBMModelKeyFilter.class)
  Key _modelKey;
  class GBMModelKeyFilter extends H2OKey { public GBMModelKeyFilter() { super("model_key",true); } }

  public static Response redirect(Request req, Key modelKey) {
    return new Response(Response.Status.redirect, req, -1, -1, "GBMModelView", "_modelKey", modelKey);
  }

  public boolean toHTML(StringBuilder sb){
    GBMModel m = DKV.get(_modelKey).get();
    m.generateHTML("GBM Model", sb);
    return true;
  }

  @Override protected Response serve() {
    return new Response(Response.Status.done,this,-1,-1,null);
  }
}
