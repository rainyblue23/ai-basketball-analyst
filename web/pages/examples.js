window.PAGES = window.PAGES || {};
window.PAGES.examples = {
  name: 'page-examples',
  data: function() { return {rows: [], loading: true, error: '', opening: ''}; },
  created: function() { this.load(); },
  methods: {
    load: function() {
      var self=this; self.loading=true; self.error='';
      window.API.getJSON(window.API.base+'/api/examples').then(function(d){self.rows=d.examples||[];})
      .catch(function(){self.error='样例暂时无法加载，请重试';}).finally(function(){self.loading=false;});
    },
    poster: function(row) { return window.API.base+'/api/examples/'+encodeURIComponent(row.id)+'/poster'; },
    time: function(t) { return window.D.mmss(t); },
    open: function(row) {
      var self=this; if(!row.ready || self.opening) return; self.opening=row.id;
      window.APP_LOAD_JOB(row.job_id).then(function(){location.hash='#/overview'; if(window.scrollTo) window.scrollTo(0,0);})
      .catch(function(){self.error='分析结果未能打开，请重试';}).finally(function(){self.opening='';});
    }
  },
  template: `<div class="page-examples"><div class="card">
    <h2 class="card-title">样例比赛</h2><p class="hint">提前分析，直接回看。自动分析与人工复核会分别标明；样例只供查看。</p>
    <div v-if="loading" role="status">正在加载样例…</div>
    <div v-else-if="error" role="alert">{{error}} <el-button text @click="load">重试</el-button></div>
    <div v-else-if="!rows.length" class="hint">样例正在准备</div>
    <div v-else class="examples-grid"><article v-for="row in rows" :key="row.id" class="example-card">
      <img v-if="row.ready" :src="poster(row)" alt="" class="example-poster" loading="lazy" width="640" height="360" />
      <div class="example-info"><h3>{{row.title}}</h3><p>{{row.description}} · {{time(row.duration)}}</p>
      <div v-if="row.ready && row.sample_review" class="example-counts"><strong>人工复核版</strong><span>运动战 {{row.sample_review.field_attempts}} 投 {{row.sample_review.field_made}} 中</span><span>罚球 {{row.sample_review.free_throw_attempts}} 投 {{row.sample_review.free_throw_made}} 中</span></div>
      <div v-else-if="row.ready" class="example-counts"><span>识别出手 {{row.shots}}</span><span>确认命中 {{row.made}}</span><span>结果未知 {{row.unknown}}</span></div>
      <el-button type="primary" :disabled="!row.ready || !!opening" :loading="opening===row.id" @click="open(row)">{{row.ready?'播放与查看分析':'分析准备中'}}</el-button>
      </div></article></div>
    </div></div>`
};
